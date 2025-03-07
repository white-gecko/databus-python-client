from enum import Enum
from typing import List, Dict, Tuple, Optional, Union
import requests
import hashlib
import json
from tqdm import tqdm
from SPARQLWrapper import SPARQLWrapper, JSON
from hashlib import sha256

__debug = False


class DeployError(Exception):
    """Raised if deploy fails"""


class BadArgumentException(Exception):
    """Raised if an argument does not fit its requirements"""


class DeployLogLevel(Enum):
    """Logging levels for the Databus deploy"""

    error = 0
    info = 1
    debug = 2


def __get_content_variants(distribution_str: str) -> Optional[Dict[str, str]]:
    args = distribution_str.split("|")

    # cv string is ALWAYS at position 1 after the URL
    # if not return empty dict and handle it separately
    if len(args) < 2 or args[1].strip() == "":
        return {}

    cv_str = args[1].strip("_")

    cvs = {}
    for kv in cv_str.split("_"):
        key, value = kv.split("=")
        cvs[key] = value

    return cvs


def __get_filetype_definition(
    distribution_str: str,
) -> Tuple[Optional[str], Optional[str]]:
    file_ext = None
    compression = None

    # take everything except URL
    metadata_list = distribution_str.split("|")[1:]

    if len(metadata_list) == 4:
        # every parameter is set
        file_ext = metadata_list[-3]
        compression = metadata_list[-2]
    elif len(metadata_list) == 3:
        # when last item is shasum:length -> only file_ext set
        if ":" in metadata_list[-1]:
            file_ext = metadata_list[-2]
        else:
            # compression and format are set
            file_ext = metadata_list[-2]
            compression = metadata_list[-1]
    elif len(metadata_list) == 2:
        # if last argument is shasum:length -> both none
        if ":" in metadata_list[-1]:
            pass
        else:
            # only format -> compression is None
            file_ext = metadata_list[-1]
            compression = None
    elif len(metadata_list) == 1:
        # let them be None to be later inferred from URL path
        pass
    else:
        # in this case only URI is given, let all be later inferred
        pass

    return file_ext, compression


def __get_extensions(distribution_str: str) -> Tuple[str, str, str]:
    extension_part = ""
    format_extension, compression = __get_filetype_definition(distribution_str)

    if format_extension is not None:
        # build the format extension (only append compression if not none)
        extension_part = f".{format_extension}"
        if compression is not None:
            extension_part += f".{compression}"
        else:
            compression = "none"
        return extension_part, format_extension, compression

    # here we go if format not explicitly set: infer it from the path

    # first set default values
    format_extension = "file"
    compression = "none"

    # get the last segment of the URL
    last_segment = str(distribution_str).split("|")[0].split("/")[-1]

    # cut of fragments and split by dots
    dot_splits = last_segment.split("#")[0].rsplit(".", 2)

    if len(dot_splits) > 1:
        # if only format is given (no compression)
        format_extension = dot_splits[-1]
        extension_part = f".{format_extension}"

    if len(dot_splits) > 2:
        # if format and compression is in the filename
        compression = dot_splits[-1]
        format_extension = dot_splits[-2]
        extension_part = f".{format_extension}.{compression}"

    return extension_part, format_extension, compression


def __get_file_stats(distribution_str: str) -> Tuple[Optional[str], Optional[int]]:
    metadata_list = distribution_str.split("|")[1:]
    # check whether there is the shasum:length tuple separated by :
    if len(metadata_list) == 0 or ":" not in metadata_list[-1]:
        return None, None

    last_arg_split = metadata_list[-1].split(":")

    if len(last_arg_split) != 2:
        raise ValueError(
            f"Can't parse Argument {metadata_list[-1]}. Too many values, submit shasum and "
            f"content_length in the form of shasum:length"
        )

    sha256sum = last_arg_split[0]
    content_length = int(last_arg_split[1])

    return sha256sum, content_length


def __load_file_stats(url: str) -> Tuple[str, int]:
    resp = requests.get(url)
    if resp.status_code > 400:
        raise requests.exceptions.RequestException(response=resp)

    sha256sum = hashlib.sha256(bytes(resp.content)).hexdigest()
    content_length = len(resp.content)
    return sha256sum, content_length


def __get_file_info(distribution_str: str) -> Tuple[Dict[str, str], str, str, str, int]:
    cvs = __get_content_variants(distribution_str)
    extension_part, format_extension, compression = __get_extensions(distribution_str)

    content_variant_part = "_".join([f"{key}={value}" for key, value in cvs.items()])

    if __debug:
        print("DEBUG", distribution_str, extension_part)

    sha256sum, content_length = __get_file_stats(distribution_str)

    if sha256sum is None or content_length is None:
        __url = str(distribution_str).split("|")[0]
        sha256sum, content_length = __load_file_stats(__url)

    return cvs, format_extension, compression, sha256sum, content_length


def create_distribution(
    url: str,
    cvs: Dict[str, str],
    file_format: str = None,
    compression: str = None,
    sha256_length_tuple: Tuple[str, int] = None,
) -> str:
    """Creates the identifier-string for a distribution used as downloadURLs in the createDataset function.
    url: is the URL of the dataset
    cvs: dict of content variants identifying a certain distribution (needs to be unique for each distribution in the dataset)
    file_format: identifier for the file format (e.g. json). If set to None client tries to infer it from the path
    compression: identifier for the compression format (e.g. gzip). If set to None client tries to infer it from the path
    sha256_length_tuple: sha256sum and content_length of the file in the form of Tuple[shasum, length].
    If left out file will be downloaded extra and calculated.
    """

    meta_string = "_".join([f"{key}={value}" for key, value in cvs.items()])

    # check whether to add the custom file format
    if file_format is not None:
        meta_string += f"|{file_format}"

    # check whether to add the custom compression string
    if compression is not None:
        meta_string += f"|{compression}"

    # add shasum and length if present
    if sha256_length_tuple is not None:
        sha256sum, content_length = sha256_length_tuple
        meta_string += f"|{sha256sum}:{content_length}"

    return f"{url}|{meta_string}"


def create_dataset(
    version_id: str,
    title: str,
    abstract: str,
    description: str,
    license_url: str,
    distributions: List[str],
    attribution: str = None,
    derived_from: str = None,
    group_title: str = None,
    group_abstract: str = None,
    group_description: str = None,
) -> Dict[str, Union[List[Dict[str, Union[bool, str, int, float, List]]], str]]:
    """
    Creates a Databus Dataset as a python dict from distributions and submitted metadata. WARNING: If file stats (sha256sum, content length)
    were not submitted, the client loads the files and calculates them. This can potentially take a lot of time, depending on the file size.
    The result can be transformed to a JSON-LD by calling json.dumps(dataset).

    Parameters
    ----------
    version_id: str
        The version ID representing the Dataset. Needs to be in the form of $DATABUS_BASE/$ACCOUNT/$GROUP/$ARTIFACT/$VERSION
    title: str
        The title text of the dataset
    abstract: str
        A short (one or two sentences) description of the dataset
    description: str
        A long description of the dataset. Markdown syntax is supported
    license_url: str
        The license of the dataset as a URI.
    distributions: str
        Distribution information string as it is in the CLI. Can be created by running the create_distribution function
    attribution: str
        OPTIONAL! The attribution information for the Dataset
    derived_from: str
        OPTIONAL! Short text explain what the dataset was
    group_title: str
        OPTIONAL! Metadata for the Group: Title. NOTE: Is only used if all group metadata is set
    group_abstract: str
        OPTIONAL! Metadata for the Group: Abstract. NOTE: Is only used if all group metadata is set
    group_description: str
        OPTIONAL! Metadata for the Group: Description. NOTE: Is only used if all group metadata is set
    """

    _versionId = str(version_id).strip("/")
    _, account_name, group_name, artifact_name, version = _versionId.rsplit("/", 4)

    # could be build from stuff above,
    # was not sure if there are edge cases BASE=http://databus.example.org/"base"/...
    group_id = _versionId.rsplit("/", 2)[0]

    artifact_id = _versionId.rsplit("/", 1)[0]

    distribution_list = []
    for dst_string in distributions:
        __url = str(dst_string).split("|")[0]
        (
            cvs,
            formatExtension,
            compression,
            sha256sum,
            content_length,
        ) = __get_file_info(dst_string)

        if not cvs and len(distributions) > 1:
            raise BadArgumentException(
                "If there are more than one file in the dataset, the files must be annotated "
                "with content variants"
            )

        entity = {
            "@type": "Part",
            "formatExtension": formatExtension,
            "compression": compression,
            "downloadURL": __url,
            "byteSize": content_length,
            "sha256sum": sha256sum,
        }
        # set content variants
        for key, value in cvs.items():
            entity[f"dcv:{key}"] = value

        distribution_list.append(entity)

    graphs = []

    # only add the group graph if the necessary group properties are set
    if None not in [group_title, group_description, group_abstract]:
        group_dict = {
            "@id": group_id,
            "@type": "Group",
        }

        # add group metadata if set, else it can be left out
        for k, val in [
            ("title", group_title),
            ("abstract", group_abstract),
            ("description", group_description),
        ]:
            group_dict[k] = val

        graphs.append(group_dict)

    # add the artifact graph

    artifact_graph = {
        "@id": artifact_id,
        "@type": "Artifact",
        "title": title,
        "abstract": abstract,
        "description": description
    }
    graphs.append(artifact_graph)

    # add the dataset graph

    dataset_graph = {
        "@type": ["Version", "Dataset"],
        "@id": _versionId,
        "hasVersion": version,
        "title": title,
        "abstract": abstract,
        "description": description,
        "license": license_url,
        "distribution": distribution_list,
    }

    def append_to_dataset_graph_if_existent(add_key: str, add_value: str):
        if add_value is not None:
            dataset_graph[add_key] = add_value

    append_to_dataset_graph_if_existent("attribution", attribution)
    append_to_dataset_graph_if_existent("wasDerivedFrom", derived_from)

    graphs.append(dataset_graph)

    dataset = {
        "@context": "https://downloads.dbpedia.org/databus/context.jsonld",
        "@graph": graphs,
    }
    return dataset


def deploy(
    dataid: Dict[str, Union[List[Dict[str, Union[bool, str, int, float, List]]], str]],
    api_key: str,
    verify_parts: bool = False,
    log_level: DeployLogLevel = DeployLogLevel.debug,
    debug: bool = False,
) -> None:
    """Deploys a dataset to the databus. The endpoint is inferred from the DataID identifier.
    Parameters
    ----------
    dataid: Dict[str, Union[List[Dict[str, Union[bool, str, int, float, List]]], str]]
        The dataid represented as a python dict. Preferably created by the creaateDataset function
    api_key: str
        the API key of the user noted in the Dataset identifier
    verify_parts: bool
        flag of the publish POST request, prevents the databus from checking shasum and content length (is already handled by the client, reduces load on the Databus). Default is False
    log_level: DeployLogLevel
        log level of the deploy output
    debug: bool
        controls whether output shold be printed to the console (stdout)
    """

    headers = {"X-API-KEY": f"{api_key}", "Content-Type": "application/json"}
    data = json.dumps(dataid)
    base = "/".join(dataid["@graph"][0]["@id"].split("/")[0:3])
    api_uri = (
        base
        + f"/api/publish?verify-parts={str(verify_parts).lower()}&log-level={log_level.name}"
    )
    resp = requests.post(api_uri, data=data, headers=headers)

    if debug or __debug:
        dataset_uri = dataid["@graph"][0]["@id"]
        print(f"Trying submitting data to {dataset_uri}:")
        print(data)

    if resp.status_code != 200:
        raise DeployError(f"Could not deploy dataset to databus. Reason: '{resp.text}'")

    if debug or __debug:
        print("---------")
        print(resp.text)


def __download_file__(url, filename):
    """
    Download a file from the internet with a progress bar using tqdm.

    Parameters:
    - url: the URL of the file to download
    - filename: the local file path where the file should be saved
    """
    print("download "+url)
    response = requests.get(url, stream=True)
    total_size_in_bytes= int(response.headers.get('content-length', 0))
    block_size = 1024 # 1 Kibibyte

    progress_bar = tqdm(total=total_size_in_bytes, unit='iB', unit_scale=True)
    with open(filename, 'wb') as file:
        for data in response.iter_content(block_size):
            progress_bar.update(len(data))
            file.write(data)
    progress_bar.close()
    if total_size_in_bytes != 0 and progress_bar.n != total_size_in_bytes:
        print("ERROR, something went wrong")


def __query_sparql__(endpoint_url, query)-> dict:
    """
    Query a SPARQL endpoint and return results in JSON format.

    Parameters:
    - endpoint_url: the URL of the SPARQL endpoint
    - query: the SPARQL query string

    Returns:
    - Dictionary containing the query results
    """
    sparql = SPARQLWrapper(endpoint_url)
    sparql.method = 'POST'
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()
    return results


def __handle__databus_file_query__(endpoint_url, query) -> List[str]:
    result_dict = __query_sparql__(endpoint_url,query)
    for binding in result_dict['results']['bindings']:
        if len(binding.keys()) > 1:
            print("Error multiple bindings in query response")
            break
        else:
            value = binding[next(iter(binding.keys()))]['value']
        yield value


def wsha256(raw: str):
    return sha256(raw.encode('utf-8')).hexdigest()


def __handle_databus_collection__(endpoint, uri: str)-> str:
    headers = {"Accept": "text/sparql"}
    return requests.get(uri, headers=headers).text


def __download_list__(urls: List[str], localDir: str):
    for url in urls:
        __download_file__(url=url,filename=localDir+"/"+wsha256(url))


def download(
    localDir: str,
    endpoint: str,
    databusURIs: List[str]
) -> None:
    """
    Download datasets to local storage from databus registry
    ------
    localDir: the local directory
    databusURIs: identifiers to access databus registered datasets
    """
    for databusURI in databusURIs:
        # dataID or databus collection
        if databusURI.startswith("http://") or databusURI.startswith("https://"):
            # databus collection
            if "/collections/" in databusURI:
                query = __handle_databus_collection__(endpoint,databusURI)
                res = __handle__databus_file_query__(endpoint, query)
            else:
                print("dataId not supported yet")
        # query in local file
        elif databusURI.startswith("file://"):
            print("query in file not supported yet")
        # query as argument
        else:
            print("QUERY {}", databusURI.replace("\n"," "))
            res = __handle__databus_file_query__(endpoint,databusURI)
            __download_list__(res,localDir)