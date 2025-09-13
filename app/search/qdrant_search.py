import json
import os

from dotenv import load_dotenv

load_dotenv()

from evaluation.eval_utils import evaluate
from qdrant_client import QdrantClient
from search.search_utils import Hit
from sentence_transformers import SentenceTransformer

# Configuration - matches your ingest script
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "medical_rag_sparse")
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DEVICE = os.getenv(
    "EMBED_DEVICE", "cpu"
)  # 'cpu' by default in containers mps on local machine

# Globals
QDRANT = None
EMBED = None


def get_qdrant_client(local=False):
    global QDRANT
    if QDRANT is None:
        if local:
            url = os.getenv("QDRANT_LOCAL_URL", "http://localhost:6333")
        else:
            url = os.getenv("QDRANT_URL", "http://qdrant:6333")
        QDRANT = QdrantClient(url, prefer_grpc=False, timeout=30)
    return QDRANT


def get_model():
    global EMBED
    if EMBED is None:
        # Use MPS on Apple Silicon; falls back to CPU if unavailable
        # device = "mps" if SentenceTransformer(MODEL_NAME).device.type != "cuda" else "cuda"
        EMBED = SentenceTransformer(MODEL_NAME, device=EMBED_DEVICE)
    return EMBED


def search_qdrant(query, top_k=5, local=False):
    """
    Simple semantic search using Qdrant for medical data
    """
    # Initialize clients (same as your ingest)
    # client = QdrantClient(QDRANT_URL)
    QDRANT_CLIENT = get_qdrant_client(local=local)
    MODEL = get_model()  # Use cached model instead of recreating

    # Create query embedding (normalized, matching ingest)
    query_vector = MODEL.encode([query], normalize_embeddings=True)[0].tolist()

    # Search
    search_results = QDRANT_CLIENT.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_vector,
        limit=top_k,
        with_payload=True,
    )

    # Extract results - adapted for your medical payload structure
    results = []
    for hit in search_results:
        # results.append({
        #    'id': hit.payload.get('id', 'unknown'),
        #    'title': hit.payload.get('title', ''),
        #    'text': hit.payload.get('text', '')[:500],  # truncate for display
        #    'source_type': hit.payload.get('source_type', ''),
        #    'source': hit.payload.get('source', ''),
        #    'score': hit.score
        # })

        results.append(
            Hit(
                id=hit.payload.get("id", "unknown"),
                title=hit.payload.get("title", ""),
                text=hit.payload.get("text", ""),
                source_type=hit.payload.get("source_type", ""),
                rrf_score=hit.score,
            )
        )

    return results


def qdrant_ids(query, limit=50):
    QDRANT_CLIENT = get_qdrant_client()
    model = get_model()
    vec = model.encode(
        [query], normalize_embeddings=True, batch_size=32, convert_to_numpy=True
    )[0]

    try:
        res = QDRANT_CLIENT.query_points(
            collection_name=COLLECTION_NAME,
            query=vec.tolist(),
            limit=limit,
            with_payload=["id"],
            with_vectors=False,
            search_params={"hnsw_ef": 128, "exact": False},
        ).points
    except Exception:
        res = QDRANT_CLIENT.search(
            collection_name=COLLECTION_NAME,
            query_vector=vec.tolist(),
            limit=limit,
            with_payload=["id"],
        )

    return [p.payload.get("id") for p in res if p.payload and p.payload.get("id")]


if __name__ == "__main__":

    ground_truth_path = (
        "/Users/jordanharris/Code/ResidentRAG/data/evaluation/ground_truth.json"
    )
    with open(ground_truth_path, "r", encoding="utf-8") as f:
        gt_raw = json.load(f)
    gt = [{"query": row["question"], "doc_id": row["doc_id"]} for row in gt_raw]

    top_k = 5
    metrics = evaluate(gt, search_qdrant, top_k=top_k, local=True)

    hit = metrics[f"Hit@{top_k}"]
    mrr = metrics[f"MRR@{top_k}"]
    map_ = metrics[f"MAP@{top_k}"]
    ndcg = metrics[f"nDCG@{top_k}"]

    print("\n📊 Qdrant Evaluation Results (aggregate, per-query metrics)")
    print(
        f"Hit@{top_k}: {hit:.3f} | MRR@{top_k}: {mrr:.3f} | MAP@{top_k}: {map_:.3f} | nDCG@{top_k}: {ndcg:.3f}"
    )

    test_queries = [
        "How effective is BA 1 immunostimulant compared to ifosfamide for treating carcinosarcoma in rats?",
        "What are the characteristics and symptoms of gastric carcinoma?",
        "What is cardiac muscle and how does its innervation differ from smooth muscle?",
        "What are the different types of blood vessels and what layers make up their walls?",
        "What are the lymphatic drainage pathways of the breast?",
    ]

    print("🔍 Testing Medical Qdrant Search")
    print("=" * 50)

    for query in test_queries:
        print(f"\n📋 Query: '{query}'")
        try:
            results = search_qdrant(query, top_k=top_k, local=True)
            print(f"✅ Found {len(results)} results:")

            for i, result in enumerate(results, 1):
                print(f"\n  {i}. Score: {result.rrf_score:.4f}")
                print(f"     Source: {result.source_type}")
                print(f"     Title:  {result.title}...")
                print(f"     Text: {result.text}...")

        except Exception as e:
            print(f"❌ Error: {e}")

        print("-" * 30)
