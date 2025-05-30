import base64
import datetime
import logging
import os
import time
from typing import List, Type, TypeVar, overload
from urllib.parse import urljoin, urlparse

import markdown
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from jinja2 import Template
from langchain_openai import ChatOpenAI
from notion_client import Client
from notion_client.errors import APIErrorCode, APIResponseError
from pydantic import BaseModel, Field
from upath import UPath

from trending_repository_summarizer.md2notion import (
    parse_markdown_to_notion_blocks,
    process_inline_formatting,
)

StructuredResponse = TypeVar("StructuredResponse", bound=BaseModel)
GITHUB_API_ENDPOINT = "https://api.github.com"
REPOSITORY_TAGS = [
    "ツール",
    "フレームワーク",
    "データセット",
    "生成AI",
    "データ分析",
    "機械学習",
    "マーケティング",
    "デザイン",
    "セキュリティ",
]


class ReferenceSite(BaseModel):
    """リポジトリの学習リソースとなるサイト"""

    name: str
    url: str


class RepositoryMetaData(BaseModel):
    """リポジトリのメタデータ"""

    repo_id: str
    repo_name: str
    repo_url: str
    description: str | None = None
    default_branch: str
    stars: int = 0
    pushed_at: datetime.datetime = datetime.datetime.min
    licenses: List[str] = []
    thumbnail_url: str | None = None
    reference_sites: List[ReferenceSite] = []
    retrieval_time: datetime.datetime | None = None


class RepositorySummary(BaseModel):
    """リポジトリの概要"""

    description: str = Field(description="リポジトリの概要")
    short_description: str = Field(description="リポジトリの簡潔な説明")
    pros: str = Field(description="リポジトリを利用するメリット")
    cons: str = Field(description="リポジトリを利用する際の注意点")
    usecases: str = Field(description="リポジトリを活用すべきケース")
    anti_usecases: str = Field(description="リポジトリを活用すべきでないケース")
    quickstart: str = Field(description="リポジトリの使い方")
    tags: List[str] = Field(description="リポジトリのタグ")


class RepositoryTags(BaseModel):
    """リポジトリのタグ一覧"""

    tags: List[str] = Field(description="リポジトリのタグ")


class RepositoryInfo(BaseModel):
    """リポジトリの情報"""

    version: str = "1.0"
    metadata: RepositoryMetaData
    summary: RepositorySummary
    readme: str


def get_trending_repositories(
    language: str, since: str, selector: str = "h2.h3.lh-condensed > a"
) -> List[str]:
    """Get trending repositories from GitHub"""
    url = f"https://github.com/trending/{language}?since={since}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")
    hrefs: list[str] = [a["href"] for a in soup.select(selector)]  # type: ignore
    repo_names = ["/".join(href.split("/")[-2:]) for href in hrefs]

    return repo_names


def get_repository_metadata(repo_id: str) -> RepositoryMetaData:
    """Get repository information from GitHub"""
    logging.info(f"Fetching metadata for {repo_id}")
    url = f"{GITHUB_API_ENDPOINT}/repos/{repo_id}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    data = response.json()

    reference_sites = [ReferenceSite(name="GitHubリポジトリ", url=data["html_url"])]
    if data["homepage"]:
        reference_sites.insert(
            0, ReferenceSite(name="ホームページ", url=data["homepage"])
        )

    return RepositoryMetaData(
        repo_id=repo_id,
        repo_name=data["name"].split("/")[-1],
        repo_url=data["html_url"],
        description=data["description"],
        default_branch=data["default_branch"],
        stars=data["stargazers_count"],
        pushed_at=datetime.datetime.fromisoformat(data["pushed_at"]),
        licenses=[data["license"]["name"]],
        reference_sites=reference_sites,
        retrieval_time=datetime.datetime.now(),
    )


def get_repository_readme(repo_id: str) -> str:
    """Get repository README from GitHub"""
    logging.info(f"Fetching README for {repo_id}")
    url = f"{GITHUB_API_ENDPOINT}/repos/{repo_id}/readme"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    data = response.json()

    # Decode base64 encoded content
    readme = base64.b64decode(data["content"]).decode("utf-8")

    return readme


def extract_thumbnail_url(metadata: RepositoryMetaData, readme: str) -> str | None:
    """Extract thumbnail URL from README"""
    html = markdown.markdown(readme)
    soup = BeautifulSoup(html, "lxml")
    img_srcs: list[str] = [img["src"] for img in soup.select("img")]  # type: ignore

    # filter out non-image URLs
    valid_exts = (".png", ".jpg", ".jpeg", ".webp")
    img_src = next(
        iter(src for src in img_srcs if urlparse(src).path.endswith(valid_exts)), None
    )
    if img_src is None:
        return None

    # convert into absolute url
    img_src = urljoin(f"{metadata.repo_url}/raw/{metadata.default_branch}/", img_src)
    return img_src


def summarize_repository(
    metadata: RepositoryMetaData, readme: str
) -> RepositorySummary:
    """Summarize README using OpenAI GPT-3"""
    # prompt cacheが効くように、READMEの内容をsystem_promptに含める
    system_prompt = (
        "あなたは世界一優秀な日本語のAIアシスタントです。"
        f"下記の文章は、{metadata.repo_name}というGitHubレポジトリのREADMEの内容を表したものです。\n"
        "このREADMEの内容をもとに、ユーザからの質問や指示に丁寧に回答してください。\n\n"
        f"{readme}"
    )

    # リポジトリの概要説明
    description = _invoke_llm(
        system_prompt=system_prompt,
        user_prompt=(
            "# 指示\n\n"
            f"{metadata.repo_name}の概要を、{metadata.repo_name}のユーザ向けに分かりやすくまとめてください。\n"
            "ただし、下記の条件をすべて厳守してください。\n\n"
            "# 条件\n\n"
            "- 枕詞や冗長な表現を避け、300文字以内の日本語で簡潔にまとめること\n"
            "- 開発者向けの情報（コミュニティ貢献やプルリクエストなど）は出力に含めないこと\n"
            "- ポイントとなるキーワードや文字列は、太字で強調すること\n"
        ),
    )

    # リポジトリの概要説明
    short_description = _invoke_llm(
        system_prompt=system_prompt,
        user_prompt=(
            "# 指示\n\n"
            f"{metadata.repo_name}の概要を、{metadata.repo_name}のユーザ向けに分かりやすくまとめてください。\n"
            "ただし、下記の条件をすべて厳守してください。\n\n"
            "# 条件\n\n"
            "- 枕詞や冗長な表現を避け、100文字以内の日本語で簡潔にまとめること\n"
            "- 開発者向けの情報（コミュニティ貢献やプルリクエストなど）は出力に含めないこと\n"
            "- ポイントとなるキーワードや文字列は、太字で強調すること\n"
            "- 出力に改行を一切含めないこと\n"
        ),
    )

    # リポジトリのメリット
    pros = _invoke_llm(
        system_prompt=system_prompt,
        user_prompt=(
            "# 指示\n\n"
            f"{metadata.repo_name}を活用するメリットを分析し、6個以内の箇条書きにまとめてください。\n"
            "ただし、下記の条件をすべて厳守してください。\n\n"
            "# 条件\n\n"
            "- 箇条書きの項目以外は何も出力しないこと\n"
            "- 各項目は、`- **<項目名>:** <項目詳細>`というフォーマットで出力すること\n"
            "- 各項目の内容は、80文字以内の日本語で簡潔にまとめること\n"
            "- 特に重要な項目を先頭に配置し、順序を意識すること\n"
            "- 重複する項目を出力しないこと\n"
        ),
    )

    # リポジトリの注意点
    cons = _invoke_llm(
        system_prompt=system_prompt,
        user_prompt=(
            "# 指示\n\n"
            f"{metadata.repo_name}を利用する際の注意点を、6個以内の箇条書きにまとめてください。\n"
            "ただし、下記の条件をすべて厳守してください。\n\n"
            "# 条件\n\n"
            "- 箇条書きの項目以外は何も出力しないこと\n"
            "- 各項目は、`- **<項目名>:** <項目詳細>`というフォーマットで出力すること\n"
            "- 各項目詳細は、80文字以内の日本語で簡潔にまとめること\n"
            "- 特に重要な項目を先頭に配置し、順序を意識すること\n"
            "- 重複する項目を出力しないこと\n"
        ),
    )

    # リポジトリを使うべきケース
    usecases = _invoke_llm(
        system_prompt=system_prompt,
        user_prompt=(
            "# 指示\n\n"
            f"{metadata.repo_name}を使うべきユースケースを、4個以内の箇条書きにまとめてください。\n"
            "ただし、下記の条件をすべて厳守してください。\n\n"
            "# 条件\n\n"
            "- 箇条書きの項目以外は何も出力しないこと\n"
            "- 各項目は、`- **<項目名>:** <項目詳細>`というフォーマットで出力すること\n"
            "- 各項目詳細は、100文字以内の日本語で簡潔にまとめること\n"
            "- 特に重要な項目を先頭に配置し、順序を意識すること\n"
            "- 重複する項目を出力しないこと\n"
        ),
    )

    # リポジトリを使うべきでないケース
    anti_usecases = _invoke_llm(
        system_prompt=system_prompt,
        user_prompt=(
            "# 指示\n\n"
            f"{metadata.repo_name}を使うべきでないユースケースを、4個以内の箇条書きにまとめてください。\n"
            "ただし、下記の条件をすべて厳守してください。\n\n"
            "# 条件\n\n"
            "- 箇条書きの項目以外は何も出力しないこと\n"
            "- 各項目は、`- **<項目名>:** <項目詳細>`というフォーマットで出力すること\n"
            "- 各項目詳細は、100文字以内の日本語で簡潔にまとめること\n"
            "- 特に重要な項目を先頭に配置し、順序を意識すること\n"
            "- 重複する項目を出力しないこと\n"
        ),
    )

    # リポジトリの使い方
    quickstart = _invoke_llm(
        system_prompt=system_prompt,
        user_prompt=f"{metadata.repo_name}を手早く使い始めるための手順を、400文字以内の日本語で、ユーザ向けに分かりやすく説明してください。",
    )

    # タグの生成
    temperature = 0.0
    while True:
        tags = _invoke_llm(
            system_prompt=system_prompt,
            user_prompt=(
                "# 指示\n\n"
                f"{metadata.repo_name}の内容をもとに、下記のタグ一覧から該当するものを0～3個選定してください。\n"
                "出力する際は、選定したタグをリスト形式で出力してください。\n\n"
                + "\n".join(f"- {tag}" for tag in REPOSITORY_TAGS)
            ),
            format=RepositoryTags,
            temperature=temperature,
        ).tags

        # 生成されたタグが有効なものであればループを抜ける
        if all(tag in REPOSITORY_TAGS for tag in tags):
            break

        # temperatureが2.0を超えた場合は警告を出して終了
        if temperature >= 2.0:
            logging.warning("Failed to generate tags")
            tags = []
            break

        # temperatureを上げて再度生成を試みる
        temperature += 0.2

    summary = RepositorySummary(
        description=description,
        short_description=short_description,
        pros=pros,
        cons=cons,
        usecases=usecases,
        anti_usecases=anti_usecases,
        quickstart=quickstart,
        tags=tags,
    )

    return summary


def format_repository_info(info: RepositoryInfo) -> str:
    # ページのmarkdownコードのテンプレート
    template_str = """\
{{ summary.description }}

[]({{ metadata.repo_url }})

---
<!-- TOC -->
---

# 1. 概要
## 1.1. {{ metadata.repo_name }}を活用するメリット

{{ summary.pros }}

## 1.2. 利用時の注意点

{{ summary.cons }}

# 2. ユースケース

## 2.1. {{ metadata.repo_name }}を使うべきケース

{{ summary.usecases }}

## 2.2. {{ metadata.repo_name }}を使うべきでないケース

{{ summary.anti_usecases }}

# 3. {{ metadata.repo_name }}の使い方

## 3.1. {{ metadata.repo_name }}の始め方

{{ summary.quickstart }}

## 3.2. 学習リソース

{% for site in metadata.reference_sites %}
- [{{ site.name }}]({{ site.url }})\
{% endfor %}\
"""
    template = Template(source=template_str)
    result = template.render(**info.model_dump())
    return result


def save_repository_info(path: UPath, info: RepositoryInfo) -> None:
    """Save repository information to a JSON file"""
    path.parent.mkdir(parents=True, exist_ok=True)
    json_text = info.model_dump_json(indent=2)
    path.write_text(json_text, encoding="utf-8")


def create_notion_page_from_md(
    title: str,
    markdown_text: str,
    cover_url: str | None = None,
    short_description: str | None = None,
    tags: List[str] | None = None,
    parent: dict | None = None,
) -> None:
    """
    Create a Notion page from Markdown text.

    Args:
        title: The title of the new Notion page.
        markdown_text: The Markdown text to be converted into a Notion page.
        cover_url: (Optional) The URL of the cover image for the new page.
            Defaults to an empty string.

    See Also:
        https://github.com/markomanninen/md2notion/blob/11bd184ca86482f200ff51060e291dd5492dd0a7/md2notionpage/core.py#L550
    """
    # initialize notion client
    notion = Client(auth=os.getenv("NOTION_API_KEY"))

    created_page = notion.pages.create(parent=parent, properties={}, children=[])
    page_id = created_page["id"]  # type: ignore

    # build page options
    page_options = {}
    if cover_url is not None:
        page_options["cover"] = {"external": {"url": cover_url}}

    # build properties
    properties = {"title": {"title": [{"type": "text", "text": {"content": title}}]}}
    if short_description is not None:
        properties["Description"] = {
            "rich_text": process_inline_formatting(short_description)
        }
    if tags is not None:
        properties["Tags"] = {"multi_select": [{"name": tag} for tag in tags]}

    notion.pages.update(
        page_id,
        properties=properties,
        **page_options,
    )

    # Iterate through the parsed Markdown blocks and append them to the created page
    blocks = parse_markdown_to_notion_blocks(markdown_text.strip())
    for block in blocks:
        try:
            notion.blocks.children.append(page_id, children=[block])
        except APIResponseError as e:
            if e.code in (
                APIErrorCode.InvalidJSON,
                APIErrorCode.InvalidRequest,
                APIErrorCode.InvalidRequestURL,
                APIErrorCode.ObjectNotFound,
                APIErrorCode.ValidationError,
            ):
                # Log the error and continue
                logging.error(f"Failed to create block: {block}\nError: {e}")
            else:
                raise


@overload
def _invoke_llm(
    system_prompt: str, user_prompt: str, *, temperature: float = 0.0
) -> str: ...


@overload
def _invoke_llm(
    system_prompt: str,
    user_prompt: str,
    format: Type[StructuredResponse],
    temperature: float = 0.0,
) -> StructuredResponse: ...


def _invoke_llm(
    system_prompt: str, user_prompt: str, format=None, temperature: float = 0.0
):
    """Invoke OpenAI's Language Model API"""
    chat = ChatOpenAI(
        model="gpt-4.1",
        openai_api_key=os.getenv("OPENAI_API_KEY"),  # type: ignore
        temperature=temperature,
    )

    if format is not None:
        chat = chat.with_structured_output(format)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    response = chat.invoke(messages)

    if format is None:
        return response.content  # type: ignore

    return response


def main() -> None:
    # Load .env file
    load_dotenv()

    # Set up logging
    if len(logging.getLogger().handlers) > 0:
        # The Lambda environment pre-configures a handler logging to stderr.
        # If a handler is already configured, `.basicConfig` does not execute.
        # Thus we set the level directly.
        logging.getLogger().setLevel(logging.INFO)
    else:
        logging.basicConfig(level=logging.INFO)

    # 収集したリポジトリ情報を保存するディレクトリ
    repo_dir = UPath("s3://github-trending-repos-info/repos/")

    for repo_id in get_trending_repositories("python", "monthly"):
        # Skip if the repository is already in the list
        if (repo_dir / f"{repo_id}.json").exists():
            continue

        # Fetcj repository metadata
        metadata = get_repository_metadata(repo_id)
        # Avoid rate limiting
        time.sleep(1)

        # Get repository README
        readme = get_repository_readme(repo_id)
        time.sleep(1)

        metadata.thumbnail_url = extract_thumbnail_url(metadata, readme)
        summary = summarize_repository(metadata, readme)

        # Build markdown text
        info = RepositoryInfo(metadata=metadata, summary=summary, readme=readme)
        repo_markdown = format_repository_info(info)

        # Upload to Notion
        database_id = os.getenv("NOTION_DATABASE_ID")
        create_notion_page_from_md(
            title=metadata.repo_name,
            markdown_text=repo_markdown,
            cover_url=metadata.thumbnail_url,
            parent={"database_id": database_id},
            short_description=summary.short_description,
            tags=summary.tags,
        )

        save_repository_info(repo_dir / f"{repo_id}.json", info)


def lambda_handler(event, context) -> str:
    """AWS Lambda用のハンドラ"""
    main()
    return "Success"


if __name__ == "__main__":
    main()
