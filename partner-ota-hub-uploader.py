#! /usr/bin/env python
#
# Copyright (c) 2017 Afero, Inc. All Rights Reserved.
#
# Python script for creating an OTA image record on the service and returning the OTA record ID.
#
# Firmware type defined in the OTA Service supported by this tool:
# - Hub (Attribute ID 2005, Type 5)
# - service: on prod 

import os
import sys
import json
import getopt
import requests
import subprocess
import time


OTA_SERVICE_HOST_URL="https://api.afero.io"

OTA_IMAGE_TYPE = 5 
addBuildType = False;

commonConfig = []
buildType_debug = False 
buildNumber = ""
createOTARecordFlag = False
uploadFromOTARecordFlag = False
access_token = None

# By default, we want to store the OTA record output file to bitbake's $TMPDIR
# this will integrate into the bitbake build environment, and Afero's
# bitbake recipe looks for the OTA record file and if found, put it in the
# rootfs system of the image.
#
# For testing, you can use -s option to skip the search for bitbake $TMPDIR
# and the OTA record is stored in the current running directory.
skip_search_tmpdir = True


#
# Default configuration file: can be changed using --conf <file>
#
configFile = "partner-ota-conf.json"


# OTA record output file
otaRecordFileName = "full_ota_record.json"


# load the configuration json file
def loadCommonConfig():
    global commonConfig
    global buildNumber

    with open(configFile) as data_file:
        data = json.load(data_file)

    
    commonConfig = data

    # replace the version from the config file to include the buildNumber and debug(d)
    version = str(commonConfig["version"])
    extension = ""
    if (buildType_debug == True):
        extension = "d"
    commonConfig["version"] = version + "." + str(buildNumber) + extension

    ts = getMillisTimestamp()
    commonConfig["createdTimestamp"] = ts
    commonConfig["updatedTimestamp"] = ts


def otaRecordForDeviceTypeExists():
    global commonConfig
    global access_token
    
    print "Check for existence -> \n"

    url="{}/v1/ota/partners/{}/pool/types/{}/names/{}/versions/{}/exists".format(
        OTA_SERVICE_HOST_URL,
        commonConfig["partnerId"],
        OTA_IMAGE_TYPE,
        commonConfig["name"],
        commonConfig["version"] 
    ) 
    headers={ 
              "Accept": "application/json",
              "Authorization": "Bearer {}".format(access_token)
            }
    response = requests.get(url, headers=headers)
    ret_val = response.json()
    if (response.status_code == 200):
        return (ret_val['value'])
    else:
        if (response.status_code == 401):
            print "Unauthorized request"
        else:
            print "Bad response ({}) from {}".format(response.status_code, url)
            print_err_response(response.json())

        exit (-1)


def createOTARecord():
    """
    Create a firmware pool image record.

    Note: Use an empty string for the url field on the request
    payload. We will update this field once we have uploaded the firmware binary file.

    POST /v1/ota/partners/{partnerId}/pool
    """
    global commonConfig
    global access_token 
   

    url_frag = "/v1/ota/partners/{}/pool"
    request_url = "%s%s" % (OTA_SERVICE_HOST_URL, url_frag)

    headers = { "Content-Type" : "application/json",
                "Accept"       : "application/json",
                "Authorization": "Bearer {}".format(access_token)}
    payload = {
                   "name"       : str(commonConfig["name"]),
                   "description": str(commonConfig["description"]),
                   "type"       : int(OTA_IMAGE_TYPE),
                   "version"    : str(commonConfig["version"]),
                   "url"        : ""
              }
    resp = requests.post(request_url.format(commonConfig["partnerId"]),
                         data=json.dumps(payload), 
                         headers=headers, 
                         timeout=None)
    if resp.status_code == 201:
        print "OTA record is created"
    else:
        print "Err: respond code {}".format(resp.status_code)
        print "    \t"
        jresp = resp.json()
        ret_text = jresp["trace"]
        print (ret_text.split("at", 1)[0])
        exit (-2)

    return json.loads(resp.text)



# Updates a firmware image in the pool.
#
# OTA API:
# PUT /v1/ota/partners/{partnerId}/pool/types/{type}/versionNumbers/{versionNumber}
#
def updateOTAImage(responseBody):
    global commonConfig
    global access_token 

    url = "{}/v1/ota/partners/{}/pool/types/{}/versionNumbers/{}".format(
                   OTA_SERVICE_HOST_URL,
                   commonConfig["partnerId"],
                   OTA_IMAGE_TYPE,
                   responseBody["versionNumber"]
                   )
    headers = { "Content-Type" : "application/json",
                "Authorization": "Bearer {}".format(access_token)}
    payload = responseBody 
                
    response = requests.put(url,
                            headers=headers,
                            json=payload,
                            timeout=None)
    if response.status_code != 204:
        print "Bad response ({}) from {}".format(response.status_code, url)
        print response.text
        exit(-7)


# 1. Uploads a firmware file to a temporary location
# 2. Moves a file from the temporary location to the permanent firmware image repo.
def uploadOTAImage(responseBody, slot):
    global commonConfig
    global access_token 


    # Upload the file to temporary spot and get the sha256 back.
    # Note we upload the unsigned file to the OTA server as it gets signed on the way out!
    filename = str(commonConfig["imageFiles"][slot]) 

    url = "{}/v1/ota/partners/{}/binaries".format(OTA_SERVICE_HOST_URL, 
                                                  commonConfig["partnerId"])
    headers = { "Content-Type" : "application/octet-stream", 
                "Accept"       : "application/json",
                "Authorization": "Bearer {}".format(access_token)}
    response = requests.post(url,
                             headers=headers,
                             files = {"file": open(filename, 'rb')},
                             timeout=None)

    if response.status_code != 200:
        print "Bad response ({}) from {} for {}".format(response.status_code, url, file)
        print response.text
        exit(-4)
    responseJson = json.loads(response.text)
    sha = responseJson['value']


    # Step 2: Move the file to the real spot and get the URL back.
    url = "{}/v1/ota/partners/{}/binaries/moveToRepository".format(
               OTA_SERVICE_HOST_URL, 
               commonConfig["partnerId"])
    headers_2 = { "Content-Type" : "application/json",
                  "Accept"       : "application/json",
                  "Authorization": "Bearer {}".format(access_token)}
    payload = { "value": str(sha) }

    response = requests.post(url, 
                            headers=headers_2,
                            data=json.dumps(payload),
                            timeout=None)
    if response.status_code != 200:
        print "Bad response ({}) from {}".format(response.status_code, url)
        print response.text
        exit(-5)


    responseJson = json.loads(response.text)

    # Update the OTA record with the new URL.
    # Depending on the OTA strategy: slot 'a' means first partition. 
    # and url2 referring to the 2nd partition (or 'b') 
    if (slot == "a"):
        responseBody["url"] = responseJson['value']
    else:
        responseBody["url2"] = responseJson['value']

    if ("id" in responseBody):
      print "Update OTA Record with the storage URL"
      updateOTAImage(responseBody)
    else:
      print "Error, No OTA Record ID Found"
      exit(-6)


# Uploading the OTA image(s)
def uploadOTAImages(responseBody):
    global commonConfig

    files = commonConfig["imageFiles"]
    for key, file in files.items():
        uploadOTAImage(responseBody, key)


def associatePoolImages(commonConfig, responseBody):
    """
    Creates a new firmware image association with a device type.
    POST /v1/ota/partners/{partnerId}/deviceTypes/{deviceTypeId}/firmwareImages
    """

    global access_token 

    url = "{}/v1/ota/partners/{}/deviceTypes/{}/firmwareImages".format(
            OTA_SERVICE_HOST_URL,
            commonConfig["partnerId"],
            commonConfig["deviceTypeId"]
            )
    headers = {
               "Content_Type" : "application/json",
               "Accept"       : "application/json",
               "Authorization": "Bearer {}".format(access_token)
              }

    if ("id" in responseBody):
        body = responseBody
    else:
       print "Error, No OTA Record ID Found"
       exit (-7)

    response = requests.post(url, headers=headers, json=body, timeout=None)
    if response.status_code != 201:
        if (response.status_code == 409):
            print "A firmware image with this type and version already exists:{}, {}".format(
                     OTA_IMAGE_TYPE,
                     commonConfig["version"])
        else:
            print "Bad response ({}) from {}".format(response.status_code, url)
            ret_val = response.json()
            print_err_response(ret_val)

        exit(-8)

    return json.loads(response.text)


def IsImageUploaded(VersionNumber):
    """
    GET /v1/ota/partners/{}/deviceTypes/{}/firmwareImages/types/{}/versionNumbers/{}
    - Retrieves a firmware image by type and version number
    """
    global access_token


    url = "{}/v1/ota/partners/{}/deviceTypes/{}/firmwareImages/types/{}/versionNumbers/{}".format(
                 OTA_SERVICE_HOST_URL,
                 commonConfig["partnerId"],
                 commonConfig["deviceTypeId"],
                 OTA_IMAGE_TYPE,
                 VersionNumber)
    headers = {
               "Accept"       : "application/json",
               "Authorization": "Bearer {}".format(access_token)
              }
    response = requests.get(url, headers=headers)
    ret_val = response.json()
    if (response.status_code == 200):
        return True
    elif (response.status_code == 404):
        return False
    else:
        if (response.status_code == 401):
            print "Unauthorized request"
        else:
            print "Bad response ({}) from {}".format(response.status_code, url)
            print_err_response(response.json())

        exit (-14)


def getMillisTimestamp():
    return int(round(time.time() * 1000))


# Request an access token for a given user 
def getAccessToken():
    global commonConfig

    url = "{}/oauth/token".format(OTA_SERVICE_HOST_URL)
    headers={ "Content-Type": "application/x-www-form-urlencoded",
              "Accept": "application/json",
	          "Authorization": "Basic {}".format(commonConfig["auth-string"]) 
            }
    payload = {"username": str(commonConfig["username"]),
               "password": str(commonConfig["userpw"]),
               "grant_type": 'password'}

    response = requests.post(url, 
                             data=payload,
                             headers=headers, 
                             timeout=None)
    jresp = response.json()
    if response.status_code == 200: 
        access_token = jresp.get('access_token')     
        print "Got access_token: {}".format(access_token)
        return access_token
    else:
        print "Bad response for token access \n"
        print "error_code:{} - {}".format(jresp["status"], jresp["error"])
        exit (-9)


def print_err_response(jresp):
    print "    \t"
    ret_text = jresp["trace"]
    print (ret_text.split("at", 1)[0])


def usage():
    print os.path.basename(sys.argv[0]) + "[-h] [-c <config_file>] [-d] [-s] -n <build number>"
    print "\t-h               : help"
    print "\t-s               : skip search for bitbake TMPDIR (** NOT for production build)"
    print "\t-n  --buildNum   : build number"
    print "\t-d  --debug      : build type debug (defaults to release)"
    print "\t-c  --conf       : path and name of the configuration file"
    print "\t    --createOTARecord  : create an OTA Record  OR  "
    print "\t    --uploadOTAImage   : upload OTA Record & image"
    exit (-10)


def parseArgs(argv):
    global buildNumber
    global buildType_debug
    global type
    global configFile
    global createOTARecordFlag
    global uploadFromOTARecordFlag
    global skip_search_tmpdir
    opts = ""

    try:
        opts, args = getopt.getopt(argv, "hdsc:n:", ["buildNum=", "debug", "conf=", "createOTARecord","uploadOTAImage"])
    except getopt.GetoptError:
        usage()

    for opt, arg in opts:
        if opt == "-h":
            usage()
        elif opt in ("-n", "--buildNum"):
            try: 
                buildNumber = arg
            except ValueError:
                usage()
        elif opt in ("-s"):
            skip_search_tmpdir = False
        elif opt in ("-d", "--debug"):
            buildType_debug = True
        elif opt in ("-c", "--conf"):
            configFile = arg
        elif opt in ("--createOTARecord"):
            createOTARecordFlag = True
        elif opt in ("--uploadOTAImage"):
            uploadFromOTARecordFlag = True


def read_bitbake_tmpdir():
    result_str = subprocess.check_output('bitbake -e | grep ^TMPDIR', shell=True)
    if "TMPDIR=" in result_str:
        dir_list = result_str.split("=")
        tmpdir = dir_list[1]
 
        # remove the newline character at end, and the quotes
        tmpdir = tmpdir.replace('\n', '')
        tmpdir = tmpdir[1:-1]
        return ( tmpdir )
    else:
        print "Error: Invalid dir {}".format(result_str)
        exit (-11)


def main(argv):
    global commonConfig
    global buildNumber
    global buildType_debug
    global deviceTypeId
    global addBuildType
    global access_token
    global skip_search_tmpdir


    parseArgs(argv)

    if not buildNumber:
        print "No build number specified"
        usage()

    loadCommonConfig()

    access_token = getAccessToken()


    if commonConfig["deviceTypeId"]:
        rec_exist = otaRecordForDeviceTypeExists()
        if (uploadFromOTARecordFlag == True and rec_exist == False):
            print "ERROR: No OTA Record for HUB image: {}, version={}. Create OTA Record first".format(
                  commonConfig["name"],
                  commonConfig["version"])
            exit (-11)
        if (createOTARecordFlag == True and rec_exist == True):
            print "ERROR: A firmware image with type {} with version {} " \
                      "already exists".format(OTA_IMAGE_TYPE,
                                              commonConfig["version"])
            exit(-12)
    else:
        print "No device type id found in partner-ota-conf.json"
        exit (-13)
   

    # read from the bitbake environment setting to get TMPDIR
    tmpdir=""
    if skip_search_tmpdir == True:
       tmpdir=read_bitbake_tmpdir()
    output_ota_rec_filename = os.path.join(tmpdir, otaRecordFileName)

    if createOTARecordFlag == True:
        print "Start to create record ....."
        otaRecord = createOTARecord()

        print "OTA Record output to: {}".format(output_ota_rec_filename)
        with open(output_ota_rec_filename, 'w') as ota_file:
           ota_file.write(json.dumps(otaRecord,sort_keys=True, indent=4, separators=(',', ': ')))
           ota_file.close()
    else:
        # upload the image:
        # - read the ota record file
        if uploadFromOTARecordFlag == True:
            with open(output_ota_rec_filename) as ota_file:
                otaRecord = json.load(ota_file)

                if (commonConfig["version"] != otaRecord["version"]):
                    print "The command request ver({}) is different from OTA Record ver({}). Check your command".format(
                           commonConfig["version"],
                           otaRecord["version"] )
                    exit (0)

                image_found = IsImageUploaded(int(otaRecord["versionNumber"]))
                if (image_found == True):
                    print "A image with type, version already uploaded:{}, {}. Exit".format(
                                              OTA_IMAGE_TYPE,
                                              commonConfig["version"])
                    exit(0)

                print "Upload the OTA Image ....."
                uploadOTAImages(otaRecord)

                print "Associate the Image with the deviceTypeId and ParnerId ....."
                associatePoolImages(commonConfig, otaRecord)
                print "Done!"


if __name__ == "__main__":
   main(sys.argv[1:])
