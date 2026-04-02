import shutil
import subprocess
import sys
import tomllib
from importlib import import_module
from pathlib import Path

LAMBDA_NAME = "trending-repository-summarizer-lambda"


def get_entry_point() -> Path:
    # pyproject.tomlの読み込み
    with open("pyproject.toml", "rb") as f:
        pyproject = tomllib.load(f)
    main_module_path = pyproject["project"]["scripts"]["main"].split(":")[0]
    main_module = import_module(main_module_path)
    entrypoint = Path(str(main_module.__file__))
    return entrypoint


def deploy_lambda():
    # Create a temporary directory
    temp_dir = Path("temp")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    # Get the entry point
    entry_point = get_entry_point()
    src_dir = entry_point.parent

    # Copy the lambda function to the temp directory
    shutil.copytree(src_dir, temp_dir)
    (temp_dir / entry_point.name).rename(temp_dir / "lambda_function.py")

    # replace all imports in the source code
    for file in temp_dir.rglob("*.py"):
        with open(file, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        with open(file, "w", encoding="utf-8") as f:
            for line in lines:
                if line.startswith(f"from {src_dir.name}"):
                    line = line.replace(f"from {src_dir.name}.", "from ")

                f.write(line + "\n")

    # Create a requirements.txt file
    subprocess.run(
        ["uv", "export", "-o", "requirements.txt", "--no-dev", "--no-hashes"],
        check=True,
    )

    # Install the dependencies in the temp directory
    subprocess.run(
        [
            "pip",
            "install",
            "-r",
            "requirements.txt",
            "-t",
            temp_dir,
            "--platform",
            "manylinux2014_x86_64",
            "--implementation",
            "cp",
            "--only-binary",
            ":all:",
            "--python-version",
            "311",
            "--abi",
            "cp311",
            "--no-deps",
        ],
        check=True,
    )

    # Zip the contents of the temp directory
    shutil.make_archive("lambda_function", "zip", temp_dir, verbose=True)

    # Clean up the temp directory
    shutil.rmtree(temp_dir)

    # Deploy the lambda function
    subprocess.run(
        [
            "aws",
            "lambda",
            "update-function-code",
            "--function-name",
            LAMBDA_NAME,
            "--zip-file",
            "fileb://lambda_function.zip",
            "--cli-connect-timeout",
            "6000",
        ],
        check=True,
    )

    # Remove the temporary files
    Path("lambda_function.zip").unlink()
    Path("requirements.txt").unlink()


if __name__ == "__main__":
    deploy_lambda()
