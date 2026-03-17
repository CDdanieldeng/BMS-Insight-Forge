# Loaders that wrap parsers and output LangChain Documents.
from retriever.loaders.factory import load_documents
from retriever.loaders.pptx_loader import load_pptx
from retriever.loaders.docx_loader import load_docx
from retriever.loaders.md_loader import load_markdown

__all__ = ["load_documents", "load_pptx", "load_docx", "load_markdown"]
