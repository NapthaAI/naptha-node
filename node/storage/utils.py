import os
import zipfile
from pathlib import Path
import io
from node.config import IPFS_GATEWAY_URL

def zip_dir(directory_path: str) -> io.BytesIO:
    """
    Zip the specified directory and return a BytesIO object containing the zip file.
    """
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for root, dirs, files in os.walk(directory_path):
            for file in files:
                file_path = os.path.join(root, file)
                zip_file.write(file_path, os.path.relpath(file_path, directory_path))
    zip_buffer.seek(0)
    return zip_buffer


def zip_directory(file_path, zip_path):
    """Utility function to recursively zip the content of a directory and its subdirectories,
    placing the contents in the zip as if the provided file_path was the root."""
    base_path_len = len(
        Path(file_path).parts
    )  # Number of path segments in the base path
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(file_path):
            for file in files:
                full_path = os.path.join(root, file)
                # Generate the archive name by stripping the base_path part
                arcname = os.path.join(*Path(full_path).parts[base_path_len:])
                zipf.write(full_path, arcname)


def get_api_url():
    domain = IPFS_GATEWAY_URL.split("/")[2]
    port = IPFS_GATEWAY_URL.split("/")[4]
    return f"http://{domain}:{port}/api/v0"

def to_multiaddr(address):
    import re

    # Check if it's already a multiaddr format
    if address.startswith('/'):
        return address
    
    # Remove http:// or https:// if present
    if address.startswith('http://'):
        address = address[7:]
    elif address.startswith('https://'):
        address = address[8:]
    
    # IP address pattern
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    
    # Split host and port
    if ':' in address:
        host, port = address.split(':')
        # Check if host is IP address
        if re.match(ip_pattern, host):
            return f'/ip4/{host}/tcp/{port}'
        else:
            return f'/dns/{host}/tcp/{port}'
    else:
        # Check if address is IP address
        if re.match(ip_pattern, address):
            return f'/ip4/{address}'
        else:
            return f'/dns/{address}'