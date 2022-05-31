# sfcc-product-extractor


# Description
This script can be used to extract needed products and its images from SFCC instance.

# Setup
First you need to setup OCAPI Data API and Webdav permissions in BM

## OCAPI API Client Setup
If you don't have OCAPI Client Key and Client Secret you need to setup it in account manager https://documentation.b2c.commercecloud.salesforce.com/DOC1/topic/com.demandware.dochelp/content/b2c_commerce/topics/account_manager/b2c_account_manager_add_api_client_id.html

## OCAPI Data API Configurations

In BM navigate to Administration >  Site Development >  Open Commerce API Settings, select DATA API and paste configurations provided below

```json
{
    "_v": "20.10",
    "clients": [
        {
            "client_id": "{{your_client_id}}",
            "resources": [
                {
                    "resource_id": "/jobs/*/executions*",
                    "methods": [
                        "post"
                    ],
                    "read_attributes": "(**)",
                    "write_attributes": "(**)"
                },
                {
                    "resource_id": "/jobs/*/executions/*",
                    "methods": [
                        "get",
                        "delete"
                    ],
                    "read_attributes": "(**)",
                    "write_attributes": "(**)"
                }
            ]
        }
    ]
}
```

## Webdav Client Setup
In BM navigate to Administration >  Organization >  WebDAV Client Permissions and paste configurations provided below

```json
{
    "client_id": "{{your_client_id}}",
    "permissions": [
        {
            "operations": [
                "read_write"
            ],
            "path": "/impex"
        },
        {
            "operations": [
                "read_write"
            ],
            "path": "/catalogs/{{your_catalog_id}}"
        }
    ]
}
```

# Script Usage
To run this script you need to have Python 3.9 or greater installed. 
To install python follow instractions here https://www.python.org/downloads/

Download code from this repository
Once code is downloaded navigate to folder 
```
cd sfcc-product-extractor
```
Create virtual env in this folder
```
python3 -m venv env
```
Activate env
```
source env/bin/activate
```
Install script dependencies
```
pip install -r requirements.txt
```
Run script
```
python main.py
```

On the first run it will generate config.json file with following structure
```json
{
    "host":"{{instance_host}}",
    "products": [],
    "client_key": "{{ocapi_client_key}}",
    "client_secret": "{{ocapi_client_secret}}!",
    "catalog_id": "{{master_catalog_id}}",
    "download_images": true
}
```



