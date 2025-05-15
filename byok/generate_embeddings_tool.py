"""Utility script to generate embeddings."""

import argparse
import json
import os
import time
from typing import Callable, Dict

import faiss
import frontmatter
import requests
from llama_index.core import Settings, SimpleDirectoryReader, VectorStoreIndex
from llama_index.core.llms.utils import resolve_llm

from llama_index.core.schema import TextNode
from llama_index.core.storage.storage_context import StorageContext
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.readers.file.flat.base import FlatReader
from llama_index.vector_stores.faiss import FaissVectorStore

def file_metadata_func(file_path: str) -> Dict:
    """Populate the docs_url and title metadata elements with docs URL and the page's title.

    Args:
        file_path: str: file path in str
    """
    title = file_path
    docs_url = file_path
    try:
        with open(file_path, "r") as file:
            first_line = file.readline()
            if first_line.startswith("#"):
                title = first_line.rstrip("\n").lstrip("# ")
                docs_url = file_path
            elif first_line.startswith("---"):
                file.close()
                post = frontmatter.load(file_path)
                title = post['title']
                docs_url = post['url']
    except Exception:  # noqa: S110
        pass
    msg = f"file_path: {file_path}, title: {title}, docs_url: {docs_url}"
    print(msg)
    return {"file_path": file_path, "title": title, "docs_url": docs_url}


if __name__ == "__main__":

    start_time = time.time()

    parser = argparse.ArgumentParser(description="Embedding CLI")
    parser.add_argument("-i", "--input-dir", help="Input directory with the markdown content")
    parser.add_argument(
        "-emd",
        "--embedding-model-dir",
        default="embeddings_model",
        help="Directory containing the embedding model",
    )
    parser.add_argument(
        "-emn",
        "--embedding-model-name",
        help="Huggingface repo id of the embedding model",
    )
    parser.add_argument(
        "-cs", "--chunk-size", type=int, default=380, help="Chunk size for embedding"
    )
    parser.add_argument(
        "-co", "--chunk-overlap", type=int, default=0, help="Chunk overlap for embedding"
    )
    parser.add_argument("-o", "--output-dir", help="Vector DB output directory")
    parser.add_argument("-id", "--index-id", help="Product index ID")
    args = parser.parse_args()
    print(f"Arguments used: {args}")

    # OLS-823: sanitize directory
    PERSIST_FOLDER = os.path.normpath("/" + args.output_dir).lstrip("/")
    if PERSIST_FOLDER == "":
        PERSIST_FOLDER = "."

    EMBEDDINGS_ROOT_DIR = os.path.abspath(args.input_dir)
    if EMBEDDINGS_ROOT_DIR.endswith("/"):
        EMBEDDINGS_ROOT_DIR = EMBEDDINGS_ROOT_DIR[:-1]

    os.environ["HF_HOME"] = args.embedding_model_dir
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    Settings.chunk_size = args.chunk_size
    Settings.chunk_overlap = args.chunk_overlap
    Settings.embed_model = HuggingFaceEmbedding(model_name=args.embedding_model_dir)
    Settings.llm = resolve_llm(None)

    embedding_dimension = len(Settings.embed_model.get_text_embedding("random text"))
    faiss_index = faiss.IndexFlatIP(embedding_dimension)
    vector_store = FaissVectorStore(faiss_index=faiss_index)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    # Load documents
    documents = SimpleDirectoryReader(
        args.input_dir,
        recursive=True,
        required_exts=[".md"],
        file_extractor={".md": FlatReader()},
        file_metadata=file_metadata_func
    ).load_data()

    # Create chunks/nodes
    nodes = Settings.text_splitter.get_nodes_from_documents(documents)

    # Create & save Index
    index = VectorStoreIndex(
        nodes,
        storage_context=storage_context,
    )
    index.set_index_id(args.index_id)
    index.storage_context.persist(persist_dir=PERSIST_FOLDER)

    metadata: dict = {}
    metadata["execution-time"] = time.time() - start_time
    metadata["llm"] = "None"
    metadata["embedding-model-name"] = args.embedding_model_name
    metadata["index-id"] = args.index_id
    metadata["vector-db"] = "faiss.IndexFlatIP"
    metadata["embedding-dimension"] = embedding_dimension
    metadata["chunk"] = args.chunk_size
    metadata["overlap"] = args.chunk_overlap
    metadata["total-embedded-files"] = len(documents)

    with open(os.path.join(PERSIST_FOLDER, "metadata.json"), "w") as file:
        file.write(json.dumps(metadata))
