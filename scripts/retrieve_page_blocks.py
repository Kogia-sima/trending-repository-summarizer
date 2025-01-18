import json
import os

import requests
from dotenv import load_dotenv


def main() -> None:
    load_dotenv()

    page_id = "17a93625bfbf802b8121db1505840837"
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    headers = {
        "Authorization": f"Bearer {os.getenv('NOTION_API_KEY')}",
        "Notion-Version": "2022-06-28",
    }

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    blocks = json.loads(response.text)["results"]

    for block in blocks:
        type_ = block["type"]
        block_info = block[type_]
        obj = {type_: block[type_]}
        print(json.dumps(obj, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
