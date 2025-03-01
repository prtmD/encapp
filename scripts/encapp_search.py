#!/usr/bin/env python3

"""Python script to for index and search in Encapp result json files.
It will search all directories below the specified one (unless --no_rec
option enabled).

Searchable properties are
* size (WxH)
* codec (partial name is fine)
* bitrate where bitrate can be
    - sctrict size, e.g. 200k
    - a range 200000-1M
* group of pictures (gop)
* frame rate

The output can either be the video source files or the json result.
"""

import argparse
import sys
import json
import os
import pandas as pd
import re

import encapp

INDEX_FILE_NAME = ".encapp_index"


def getProperties(options, json):
    data = getData(options, True)
    _, filename = os.path.split(json)
    row = data.loc[data["filename"].str.contains(filename)]
    return row


def getFilesInDir(directory, recursive):
    regexp = "^encapp_.*json$"
    files = []
    for path in os.listdir(directory):
        full_path = os.path.join(directory, path)
        if os.path.isfile(full_path):
            if re.match(regexp, path):
                files.append(full_path)
        else:
            if recursive:
                files = files + getFilesInDir(full_path, recursive)
    return files


common_data = ["common", "input", "configure"]


def dict_flatten(test):
    key_list = []
    val_list = []
    for k1, v1 in test.items():
        if k1 in common_data:
            for k2, v2 in v1.items():
                if k2 == "resolution":
                    sizes = v2.split("x")
                    key_list.append(f"{k1}.width")
                    key_list.append(f"{k1}.height")
                    val_list.append(int(sizes[0]))
                    val_list.append(int(sizes[1]))
                    continue
                key_list.append(f"{k1}.{k2}")
                val_list.append(v2)
    return key_list, val_list


def indexDirectory(options, recursive):
    files = getFilesInDir(f"{options.path}", recursive)
    settings = []

    key_list = []
    for filename in files:
        try:
            # get device data
            device_filename = os.path.join(os.path.dirname(filename), "device.json")
            with open(device_filename) as f:
                device_info = json.load(f)
            model = device_info.get("props", {}).get("ro.product.model", "")
            platform = device_info.get("props", {}).get("ro.board.platform", "")
            serial = device_info.get("props", {}).get("ro.serialno", "")
            # get experiment data
            with open(filename) as f:
                data = json.load(f)
                key_list, val_list = dict_flatten(data["test"])
                settings.append(
                    [
                        model,
                        platform,
                        serial,
                        filename,
                        data["encodedfile"],
                        *val_list,
                        data["meanbitrate"],
                    ]
                )
        except Exception as exc:
            print("json " + filename + ", load failed: " + str(exc))

    labels = (
        ["model", "platform", "serial", "filename", "encodedfile"]
        + key_list
        + ["meanbitrate"]
    )
    pdata = pd.DataFrame.from_records(settings, columns=labels, coerce_float=True)
    pdata.to_csv(f"{options.path}/{INDEX_FILE_NAME}", index=False)


def getData(options, recursive):
    index_filename = f"{options.path}/{INDEX_FILE_NAME}"
    try:
        data = pd.read_csv(index_filename)
    except Exception:
        if not os.path.exists(index_filename):
            sys.stderr.write(f"Warning: Recreating {index_filename}\n")
        else:
            sys.stderr.write(f"Error when reading {index_filename}, reindex\n")
        indexDirectory(options, recursive)
        try:
            data = pd.read_csv(index_filename)
        except Exception:
            sys.stderr.write(f"Failed to read index file: {index_filename}")
            exit(-1)
    return data


def search(options):
    data = getData(options, not options.no_rec)
    data["configure.bitrate"] = data["configure.bitrate"].apply(
        lambda x: encapp.convert_to_bps(x)
    )
    if options.codec:
        data = data.loc[data["configure.codec"].str.contains(options.codec, na=False)]
    if options.bitrate:
        ranges = options.bitrate.split("-")
        vals = []
        for val in ranges:
            bitrate = encapp.convert_to_bps(val)
            vals.append(int(bitrate))

        if len(vals) == 2:
            data = data.loc[
                (data["configure.bitrate"] >= vals[0])
                & (data["configure.bitrate"] <= vals[1])
            ]
        else:
            data = data.loc[data["configure.bitrate"] == vals[0]]
    if options.gop:
        data = data.loc[data["configure.iFrameInterval"] == options.gop]
    if options.fps:
        data = data.loc[data["configure.framerate"] == options.fps]
    if options.size:
        sizes = options.size.split("x")
        if len(sizes) == 2:
            data = data.loc[
                (data["configure.width"] == int(sizes[0]))
                & (data["configure.height"] == int(sizes[1]))
            ]
        else:
            data = data.loc[
                (data["configure.width"] == int(sizes[0]))
                | (data["configure.height"] == int(sizes[0]))
            ]

    return data


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("path", nargs="?", help="Search path, default current")
    parser.add_argument("-s", "--size", default=None)  # WxH
    parser.add_argument("-c", "--codec", default=None)
    parser.add_argument("-b", "--bitrate", default=None)
    parser.add_argument("-g", "--gop", type=int, default=None)
    parser.add_argument("-f", "--fps", type=float, default=None)
    parser.add_argument("--no_rec", action="store_true")
    parser.add_argument("-i", "--index", action="store_true")
    parser.add_argument("-v", "--video", action="store_true")
    parser.add_argument("-p", "--print_data", action="store_true")

    options = parser.parse_args()
    if options.path is None:
        options.path = os.getcwd()

    if options.index:
        indexDirectory(options, not options.no_rec)

    data = search(options)
    data = data.sort_values(
        by=[
            "model",
            "configure.codec",
            "configure.iFrameInterval",
            "configure.framerate",
            "configure.height",
            "configure.bitrate",
        ]
    )
    if options.print_data:
        for _index, row in data.iterrows():
            print(
                "{:s},{:s},{:s},{:d},{:d},{:d},{:d},{:d},{:d}".format(
                    row["filename"],
                    row["encodedfile"],
                    row["configure.codec"],
                    row["configure.iFrameInterval"],
                    row["configure.framerate"],
                    row["configure.width"],
                    row["configure.height"],
                    row["configure.bitrate"],
                    row["meanbitrate"],
                )
            )
    else:
        files = data["filename"].values
        for fl in files:
            directory, filename = os.path.split(fl)
            if options.video:
                video = data.loc[data["filename"] == fl]
                name = directory + "/" + video["media"].values[0]
            else:
                name = fl
            print(name)


if __name__ == "__main__":
    main()
