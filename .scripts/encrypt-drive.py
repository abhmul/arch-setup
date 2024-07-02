import argparse
from fnmatch import fnmatch
import os
from os.path import isfile, join, exists
import subprocess
from termcolor import colored
import sys
import functools

from tqdm import tqdm

parser = argparse.ArgumentParser()
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument("-e", "--encrypt", action="store_true")
group.add_argument("-d", "--decrypt", action="store_true")
parser.add_argument("-p", "--password", default="", type=str)
parser.add_argument(
    "--delete",
    dest="run_aescrypt",
    action="store_false",
    help="No encryption or decryption, just delete",
)
parser.add_argument(
    "--no_ignore", action="store_true", help="Don't use .aesignore file"
)

IGNORE_FILENAME = ".aesignore"
EXTENSION_GLOB = "*.aes"


def union(args):
    return functools.reduce(lambda x, y: x | y, args, set())


def accept_name(filename: str, exclude_patterns: list, include_patterns: list) -> bool:
    return not any(fnmatch(filename, p) for p in exclude_patterns) and all(
        fnmatch(filename, p) for p in include_patterns
    )


def filter_files(root: str, excludes: list, filename_includes: list) -> set:
    items = os.listdir(root)
    filenames = [n for n in items if isfile(join(root, n))]
    dirnames = [n for n in items if not isfile(join(root, n))]

    accepted_fnames = set(
        join(root, n) for n in filenames if accept_name(n, excludes, filename_includes)
    )
    # We only check filenames for includes rules
    accepted_dirs = set(join(root, d) for d in dirnames if accept_name(d, excludes, []))

    return accepted_fnames | union(
        filter_files(d, excludes, filename_includes) for d in accepted_dirs
    )


def generate_message(filenames: list, remove: bool) -> str:
    change = colored("-", "red") if remove else colored("+", "green")
    message = "\n".join(change + " " + n for n in filenames)
    return message


def delete_encrypted_files(filenames: list):
    print("We will delete these files:")
    print(generate_message(filenames, remove=True))
    response = input("Are you sure you want to delete [y/N]: ")
    if response.lower() == "y":
        for n in filenames:
            # print(f'fake deleting {n}')
            os.remove(n)
        print("All files deleted!")
    elif response.lower() not in {"", "n"}:
        raise ValueError(f"Invalid input {response}")


def build_command(encrypt: bool, decrypt: bool, filenames: list, password) -> list:
    command = (
        ["aescrypt"]
        + (["-e"] if encrypt else [])
        + (["-d"] if decrypt else [])
        + (["-p", password] if password else [])
        + filenames
    )
    return command


def run_aescrypt(encrypt: bool, decrypt: bool, filenames: list, password="") -> list:
    # This should be guaranteed by our argument parser
    assert encrypt ^ decrypt

    operation = "encrypt" if encrypt else "decrypt"
    print(f"We will {operation} these files:")
    print(generate_message(filenames, remove=False))
    response = input(f"Are you sure you want to {operation} [Y/n]: ")
    if response.lower() in {"", "y"}:
        # DEBUGGING
        print("DEBUGGING")
        BAD = []
        for fname in tqdm(filenames):
            process = subprocess.run(build_command(encrypt, decrypt, [fname], password))
            if process.returncode != 0:
                BAD.append(fname)
        print("Files we were unable to decrypt")
        print(generate_message(BAD, remove=True))
    elif response.lower() == "n":
        sys.exit(f"No {operation} will be run. Terminating...")
    else:
        raise ValueError(f"Invalid input {response}")


if __name__ == "__main__":
    args = parser.parse_args()
    # DEBUGGING
    # assert args.decrypt
    print(args.password)
    # assert False

    excludes = [IGNORE_FILENAME]
    if not args.no_ignore and exists(IGNORE_FILENAME):
        print("Found an ignore file")
        with open(IGNORE_FILENAME) as ignore_file:
            excludes += list(ignore_file.read().splitlines())

    if args.encrypt:
        excludes += [EXTENSION_GLOB]

    filename_includes = []
    if args.decrypt:
        filename_includes += [EXTENSION_GLOB]

    fnames = sorted(list(filter_files(".", excludes, filename_includes)))
    if args.run_aescrypt:
        run_aescrypt(args.encrypt, args.decrypt, fnames, args.password)

    delete_encrypted_files(fnames)

