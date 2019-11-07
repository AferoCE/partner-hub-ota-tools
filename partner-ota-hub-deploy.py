#! /usr/bin/env python
#
# Copyright (c) 2017 Afero, Inc. All Rights Reserved.
#
# Python script for deploying an OTA image to a device
#
# Firmware type defined in the OTA Service supported by this tool:
# - Hub (Attribute ID 2005, Type 5)
# - service: on prod 

import os
import sys
import json
import getopt
import requests
#from subprocess import Popen, PIPE
import time


OTA_SERVICE_HOST_URL="https://api.afero.io"
OTA_IMAGE_TYPE = 5

commonConfig = []
access_token = None
deviceId  = None
imageId   = None 
listFlag  = False

# 
# Default configuration file: can be changed using --conf <file> option
# 
configFile = "partner-ota-conf.json"


#
# load the configuration json file
#
def loadCommonConfig():
    global commonConfig

    with open(configFile) as data_file:
        data = json.load(data_file)

    commonConfig = data

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


def listOTAImages():
    global commonConfig
    global access_token 


    url="{}/v1/ota/partners/{}/deviceTypes/{}/firmwareImages/types/{}".format(
                                                     OTA_SERVICE_HOST_URL,
	                                                 commonConfig["partnerId"],
                                                     commonConfig["deviceTypeId"],
                                                     OTA_IMAGE_TYPE)
    headers={
              "Accept": "application/json",
              "Authorization": "Bearer {}".format(access_token)
            }

    response = requests.get(url, headers=headers)
    ret_val = response.json()
    if (response.status_code == 200):
        content = ret_val['content']
        print "\n----  List of HUB FULL OTA images ---- \n"
        print "partnerId   : {}".format(commonConfig["partnerId"])
        print "deviceTypeId: {}\n".format(commonConfig["deviceTypeId"])

        print "Total Number of Images: {}".format(ret_val['totalElements'])
        print "{0:<10}  {1:<15}  {2:<30}  {3:<30}".format("Image Id", "Version", "Name", "Description")
        print "{0:<10}  {1:<15}  {2:<30}  {3:<30}".format("-" * 10, "-" * 15 , "-" * 30, "-" * 30)

        for page in range (0, ret_val['totalPages']):
            for ele in range (0, ret_val['totalElements']):
                record = content[ele]
                print "{0:<10}  {1:<15}  {2:<30}  {3:<30}".format(
                      record['id'], record['version'], record['name'], record['description'])
    else:
        if (response.status_code == 401):
            print "Unauthorized request"
        else:
            print "Bad response ({}) from {}".format(response.status_code, url)

        print_err_response(response.json())
        exit (-2)



def deployOTAImage():
    global commonConfig
    global access_token 


    url="{}/v1/ota/partners/{}/deviceTypes/{}/firmwareImages/{}/push".format(
               OTA_SERVICE_HOST_URL,
               commonConfig["partnerId"],
               commonConfig["deviceTypeId"],
               imageId
               )
    headers={
              "Accept": "application/json",
              "Authorization": "Bearer {}".format(access_token)
            }
    payload={
              "value": deviceId
            }
    
    response = requests.put(url, 
                            headers=headers,
                            json=payload,
                            timeout=None)
    if (response.status_code == 202):
        print "\nRequest accepted for processing\n"
    else:
        ret_val = response.json()
        if (response.status_code == 401):
            print "Unauthorized request"
        else:
            print "Bad response ({}) from {}".format(response.status_code, url)
            print_err_response(response.json())

        exit (-3)
    

def usage():
    print os.path.basename(sys.argv[0]) + "[-h] [-c <config_file>] -d <deviceId> -i <imageId> " 
    print "\t-h           : help"
    print "\t-c  --conf   : path and name of the configuration file"
    print "\t-l  --list   : list the OTA images for the partner and deviceType only, without deploying"
    print "\t-d  --device : deviceId of the device receiving the OTA image"  
    print "\t-i  --imageId: unique numerical Id for the uploaded OTA Image"  
    exit (-10)


def parseArgs(argv):
    global configFile
    global listFlag 
    global deviceId 
    global imageId 

    opts = ""

    try:
        opts, args = getopt.getopt(argv, "hd:c:i:l", ["conf=", "device=", "imageId=", "list"])
    except getopt.GetoptError:
        usage()

    for opt, arg in opts:
        if opt == "-h":
            usage()
        elif opt in ("-c", "--conf"):
            configFile = arg
        elif opt in ("-l", "--list"):
            listFlag = True   
        elif opt in ("-d", "--device"):
            deviceId=arg 
        elif opt in ("-i", "--image"):
            imageId = int(arg)
        else:
            usage()


def main(argv):
    global commonConfig
    global deviceTypeId
    global access_token


    parseArgs(argv)

    if (not deviceId) and (listFlag == False):
        print "Device Id is required for OTA delopyment"
        usage()

    loadCommonConfig()

    access_token = getAccessToken()


    if listFlag == True:
        listOTAImages()
    else:
        if (deviceId != None) and (imageId != None):
                print "Initiate OTA Image deploying ..... "
                deployOTAImage()
        else:
           print ("Please specify deviceId and imageId for OTA deployment")



if __name__ == "__main__":
   main(sys.argv[1:])
