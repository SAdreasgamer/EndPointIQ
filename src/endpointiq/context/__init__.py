"""Context engine — MRC algorithm, compression, token counting.

The core innovation: extracts minimal relevant code context from the
knowledge graph using Personalized PageRank and compresses it with
a 4-stage pipeline to fit within LLM token budgets.
"""
