"""Client tests"""
import pytest
from databusclient.client import create_dataset, create_distribution, __get_file_info
from collections import OrderedDict


EXAMPLE_URL = "https://raw.githubusercontent.com/dbpedia/databus/608482875276ef5df00f2360a2f81005e62b58bd/server/app/api/swagger.yml"


def test_distribution_cases():

    metadata_args_with_filler = OrderedDict()

    metadata_args_with_filler["type=config_source=databus"] = ""
    metadata_args_with_filler["yml"] = None
    metadata_args_with_filler["none"] = None
    metadata_args_with_filler[
        "79582a2a7712c0ce78a74bb55b253dc2064931364cf9c17c827370edf9b7e4f1:56737"
    ] = None

    # test by leaving out an argument each
    artifact_name = "databusclient-pytest"
    uri = "https://raw.githubusercontent.com/dbpedia/databus/master/server/app/api/swagger.yml"
    parameters = list(metadata_args_with_filler.keys())

    for i in range(0, len(metadata_args_with_filler.keys())):

        if i == 1:
            continue

        dst_string = f"{uri}"
        for j in range(0, len(metadata_args_with_filler.keys())):
            if j == i:
                replacement = metadata_args_with_filler[parameters[j]]
                if replacement is None:
                    pass
                else:
                    dst_string += f"|{replacement}"
            else:
                dst_string += f"|{parameters[j]}"

        print(f"{dst_string=}")
        (
            name,
            cvs,
            formatExtension,
            compression,
            sha256sum,
            content_length,
        ) = __get_file_info(artifact_name, dst_string)

        created_dst_str = create_distribution(
            uri, cvs, formatExtension, compression, (sha256sum, content_length)
        )

        assert dst_string == created_dst_str


def test_empty_cvs():

    dst = [create_distribution(url=EXAMPLE_URL, cvs={})]

    dataset = create_dataset(
        version_id="https://dev.databus.dbpedia.org/user/group/artifact/1970.01.01/",
        title="Test Title",
        abstract="Test abstract blabla",
        description="Test description blabla",
        license_url="https://license.url/test/",
        distributions=dst,
    )

    correct_dataset = {
        "@context": "https://downloads.dbpedia.org/databus/context.jsonld",
        "@graph": [
            {
                "@type": "Dataset",
                "@id": "https://dev.databus.dbpedia.org/user/group/artifact/1970.01.01#Dataset",
                "hasVersion": "1970.01.01",
                "title": "Test Title",
                "abstract": "Test abstract blabla",
                "description": "Test description blabla",
                "license": "https://license.url/test/",
                "distribution": [
                    {
                        "@id": "https://dev.databus.dbpedia.org/user/group/artifact/1970.01.01#artifact.yml",
                        "@type": "Part",
                        "file": "https://dev.databus.dbpedia.org/user/group/artifact/1970.01.01/artifact.yml",
                        "formatExtension": "yml",
                        "compression": "none",
                        "downloadURL": EXAMPLE_URL,
                        "byteSize": 59986,
                        "sha256sum": "088e6161bf8b4861bdd4e9f517be4441b35a15346cb9d2d3c6d2e3d6cd412030",
                    }
                ],
            }
        ],
    }

    assert dataset == correct_dataset
