import os
from pathlib import Path

from ppteval.utils.onedrive import OneDriveClient


def hydrate_onedrive_folders(client_id: str, root_path: str, local_dir: str):
    # Initialize OneDrive client with proper root_path
    client = OneDriveClient(client_id=client_id, root_path=root_path)

    # Convert local_dir to Path object for easier manipulation
    local_path = Path(local_dir)

    if not local_path.exists():
        raise FileNotFoundError(f"Local directory does not exist: {local_dir}")

    print(f"Starting upload of '{local_dir}' to OneDrive root path: '{root_path}'")

    # Use the upload_directory_recursive method to copy the entire subtree
    # The contents of local_dir will be uploaded to the root_path
    client.upload_directory_recursive(local_dir, "")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Upload local directory structure to OneDrive")
    parser.add_argument("--client-id", required=False, help="Azure app client ID")
    parser.add_argument(
        "--root-folder",
        default="Documents/PPTEval",
        help="Root folder path in OneDrive (default: Documents/PPTEval)",
    )
    parser.add_argument(
        "--local-dir",
        default="data/files",
        help="Local directory to upload (default: data/files)",
    )

    args = parser.parse_args()

    if not args.client_id:
        if "CLIENT_ID" in os.environ:
            args.client_id = os.environ["CLIENT_ID"]
        elif os.path.exists(".env"):
            from dotenv import load_dotenv

            load_dotenv()
            args.client_id = os.getenv("CLIENT_ID")
    if not args.client_id:
        raise ValueError("CLIENT_ID must be provided either as an argument or in the .env file.")

    print(f"Uploading '{args.local_dir}' to OneDrive path: '{args.root_folder}'")
    hydrate_onedrive_folders(args.client_id, args.root_folder, args.local_dir)
