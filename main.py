import os
import json
import sys
import threading
import typing
import httpx
import time
import xml.etree.ElementTree as ET
from queue import Queue
from zipfile import ZipFile
from rich.console import Console
from webdav4.client import Client as WebDavClient


CONFIG_STRUCT = {
    "host":"",
    "products": [],
    "client_key": "",
    "client_secret": "",
    "catalog_id": "",
    "download_images": False
}


class SFCCOAuth(httpx.Auth):
    OAUTH_BASE_URL = "https://account.demandware.com/dwsso/oauth2/access_token"

    def __init__(self, client_key:str=None, client_secret:str=None, lock:threading.Lock=None) -> None:
        super().__init__()
        self.client_secret = client_secret
        self.client_key = client_key
        self.token = None
        self._lock = lock
        self._console = Console()
        

    def auth_flow(self, request: httpx.Request) -> typing.Generator[httpx.Request, httpx.Response, None]:
        if self.token == None:
            
            if self._lock != None:
                self._lock.acquire()

            self._set_token()

            if self._lock != None:
                self._lock.release()
        
        request.headers['Authorization'] = "Bearer {}".format(self.token)

        resp = yield request

        if resp.status_code == 401:
            self._console.log("SFCC Oauth Token expired or not valid, getting new token...", style="yellow")

            if self._lock != None:
                self._lock.acquire()

            self._set_token()

            if self._lock != None:
                self._lock.release()

            request.headers['Authorization'] = "Bearer {}".format(self.token)
            yield request
    
    
    def _set_token(self) -> None:
        client = httpx.Client(timeout=30)
        auth = httpx.BasicAuth(self.client_key, self.client_secret)
        resp = client.post(self.OAUTH_BASE_URL, auth=auth, params={"grant_type":"client_credentials"})

        if resp.status_code == 200 or resp.status_code == 202:
            resp_data  = resp.json()
            self.token = resp_data.get("access_token", None)
        else:
            self._console.log("ERROR: Failed to get ouath token", style="red")
            

class CatalogParser():
    NS = {"default": "http://www.demandware.com/xml/impex/catalog/2006-10-31"}

    def __init__(self, catalog_id:str) -> None:
        ET.register_namespace("", "http://www.demandware.com/xml/impex/catalog/2006-10-31")
        self.catalog_id = catalog_id
        self.catalog_xml_tree:ET.Element = None 
        self.image_mapping:typing.Dict = {}
        self._output_xml_tree:ET.Element = None
        self._product_indexes:typing.Dict = {}
        self._pending_products:typing.Set = set()
        self._console = Console()


    def load_file(self, file:typing.Any):
        console.log("Loading catalog file...", style="blue")

        self.catalog_xml_tree = ET.parse(file).getroot()
        self._output_xml_tree = ET.Element("catalog", {
            "catalog-id":  self.catalog_id,
            "xmlns": "http://www.demandware.com/xml/impex/catalog/2006-10-31"
        })


    def extract_products(self, products:typing.List[str], include_images:bool) -> None:
        if self.catalog_xml_tree != None:
            console.log("Extracting products...", style="blue")

            self.products = self.catalog_xml_tree.findall("default:product", self.NS)

            for ind, product_elem in enumerate(self.products):
                id = product_elem.get("product-id")

                if id in products:
                    self._output_xml_tree.append(product_elem)
                    self._check_productsets(product_elem)
                    self._check_productvariants(product_elem)
                    
                    if include_images:
                        self._check_product_images(product_elem)

                else:
                    self._product_indexes[id] = ind

            self._process_pending_products(include_images)
            self._save()

            console.log("Modified catalog saved", style="green")


    def _process_pending_products(self, include_images):
        while len(self._pending_products) > 0:
            temp_set = self._pending_products.copy()

            for product_id in temp_set:
                self._pending_products.remove(product_id)

                if product_id in self._product_indexes:
                    product_elem = self.products[self._product_indexes.get(product_id)]

                    self._output_xml_tree.append(product_elem)
                    self._check_productsets(product_elem)
                    self._check_productvariants(product_elem)
                    
                    if include_images:
                        self._check_product_images(product_elem)


    def _check_product_images(self, product_elem:ET.Element):
        image_block = product_elem.find("default:images", self.NS)

        if image_block != None:
            product_id = product_elem.get("product-id")
            self.image_mapping[product_id] = set()

            for image_group in image_block.findall("default:image-group", self.NS):
                for image in image_group.findall("default:image", self.NS):
                    self.image_mapping[product_id].add(image.get("path"))


    def _check_productsets(self, product_elem:ET.Element):
        product_sets = product_elem.find("default:product-set-products", self.NS)
        
        if product_sets != None:
            for elem in product_sets.findall("default:product-set-product", self.NS):
                self._pending_products.add(elem.get("product-id", ""))


    def _check_productvariants(self, product_elem:ET.Element):
        product_variantions = product_elem.find("default:variations", self.NS)

        if product_variantions != None:
            variants = product_variantions.find("default:variants", self.NS)

            if variants != None:
                for elem in variants.findall("default:variant", self.NS):
                    self._pending_products.add(elem.get("product-id", ""))


    def _save(self):
        ET.ElementTree(self._output_xml_tree).write("./src/catalog.xml")


class CatalogImages():
    def __init__(self, host:str, client_key:str, client_secret:str, catalog_id:str, images_mapping:typing.Dict) -> None:
        self.images_mapping = images_mapping
        self._queue = Queue()
        self._lock = threading.Lock()
        self._num_cpus = os.cpu_count()
        self._auth = SFCCOAuth(client_key, client_secret, self._lock)
        self._client = WebDavClient(f"https://{host}/on/demandware.servlet/webdav/Sites/Catalogs/{catalog_id}", self._auth)
        self._console = Console()


    def download_imapges(self, folder_path):
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)

        for _ in range(self._num_cpus):
            threading.Thread(target=self._donwload_worker, daemon=True).start()

        for k,v in self.images_mapping.items():
            self._queue.put((k, v))

        self._queue.join()


    def _donwload_worker(self):
        while True:
            product_id, images = self._queue.get()

            self._console.log(f"Downloading images for product: {product_id}", style="blue")
            
            for image_path in images:
                self._download_image(image_path)
            
            self._console.log(f"Download of images complete for product {product_id}", style="green")
            self._queue.task_done()
    

    def _download_image(self, image_path:str):
        path_parts = image_path.split("/")

        if len(path_parts) > 1:
            location = "/".join(path_parts[0:-1])
            dst_path = f"./src/images/{location}"
            
            self._lock.acquire()

            if not os.path.exists(dst_path):
                os.makedirs(dst_path)

            self._lock.release()

        try:
            self._client.download_file(from_path=f"default/{image_path}", to_path=f"./src/images/{image_path}")
        except: 
            self._console.log(f"ERROR: Failed to download image from: {image_path}", style="red")



class ExportJob():
    ENDPOINTS = {
        "execute": "https://{}/s/Sites-Site/dw/data/v21_10/jobs/sfcc-site-archive-export/executions",
        "status": "https://{0}/s/Sites-Site/dw/data/v21_10/jobs/sfcc-site-archive-export/executions/{1}"
    }


    def __init__(self, host:str, auth:httpx.Auth, catalog_id:str) -> None:
        self.host = host
        self.auth = auth
        self.catalog_id = catalog_id
        self._exec_id = None


    def execute_job(self) -> dict:
        client = httpx.Client(timeout=30)
        job_result = {"is_running": False, "status_code": 0}
        req_body = {
            "export_file": "master_catalog",
            "overwrite_export_file": True,
            "data_units": {
                "catalogs": {
                    f"{self.catalog_id}": True
                }
            }
        }

        resp = client.post(self.ENDPOINTS["execute"].format(self.host), auth=self.auth, json=req_body)

        if resp.status_code == 202:
            resp_data = resp.json()
            job_result["is_running"] = True
            self._exec_id = resp_data.get("id", None)
        else:
            job_result["status_code"] = resp.status_code

        return job_result
    

    def is_running(self) -> bool:
        client = httpx.Client(timeout=30)
        resp = client.get(self.ENDPOINTS["status"].format(self.host, self._exec_id), auth=self.auth)

        if resp.status_code == 200:
            resp_data = resp.json()
            exec_status = resp_data.get("execution_status", None)

            return False if exec_status == "finished" else True
            
        return False



if __name__ == "__main__":
    console = Console()
    
    if not os.path.exists("config.json"):
        with open("config.json", "w") as config_file:
            config_file.write(json.dumps(CONFIG_STRUCT, indent=4))
            console.log("Config file was not found, new config file was initialized", style="blue")
        sys.exit(1)

    with open("config.json", "r") as config_file:
        config = json.load(config_file)
        host = config.get("host", "")
        client_key = config.get("client_key", "")
        client_secret = config.get("client_secret", "")
        catalog_id = config.get("catalog_id", "")
        products = config.get("products", [])
        download_images = config.get("download_images", False)

        if not client_key or not client_secret:
            console.log("ERROR: Client Key or Client Secret is missing", style="red")
            sys.exit(1)

        if not host:
            console.log("ERROR: Instance host not provided", style="red")
            sys.exit(1)

        if not catalog_id:
            console.log("ERROR: Catalog ID is missing", style="red")
            sys.exit(1)

        if not os.path.exists("./temp"):
            os.mkdir("temp")

        if not os.path.exists("./src"):
            os.mkdir("src")

        ouath = SFCCOAuth(client_key=client_key, client_secret=client_secret)
        catalog_job = ExportJob(host, ouath, catalog_id)

        console.log("Executing export Job...", style="blue")

        job_res = catalog_job.execute_job()

        if not job_res["is_running"]:
            console.log(f"ERROR: Failed to start job, Response Code: {job_res['status_code']}", style="red")
            sys.exit(1)

        while catalog_job.is_running():
            time.sleep(10)

        webdav_client = WebDavClient(f"https://{host}/on/demandware.servlet/webdav/Sites/Impex/src/instance", auth=ouath)

        if not webdav_client.exists("master_catalog.zip"):
            console.log("ERROR: Could not locate catalog export archive on webdav", style="red")
            sys.exit(1)

        console.log("Downloading export file...", style="blue")
       
        webdav_client.download_file(from_path="master_catalog.zip", to_path="./temp/master_catalog.zip")

        if not os.path.exists("./temp/master_catalog.zip"):
            console.log("ERROR: could not find catalog archive", style="red")
            sys.exit(1)

        console.log("Export file downloaded, removing file from wedav", style="green")

        webdav_client.remove("master_catalog.zip")

        parser = CatalogParser(catalog_id)

        with ZipFile("./temp/master_catalog.zip", mode="r") as zip:
            with zip.open(f"master_catalog/catalogs/{catalog_id}/catalog.xml") as catalog_file:
                parser.load_file(catalog_file)
                parser.extract_products(products, download_images)

        if len(parser.image_mapping.keys()):
            image_handler = CatalogImages(host, client_key, client_secret, catalog_id, parser.image_mapping)
            image_handler.download_imapges("./src/images")

        os.remove("./temp/master_catalog.zip")
        sys.exit(0)
        