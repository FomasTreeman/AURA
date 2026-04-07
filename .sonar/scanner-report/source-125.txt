"""
Generate 8 dummy PDF documents for testing AURA's RAG pipeline.
Run from project root: python scripts/generate_test_docs.py
"""
import textwrap
from pathlib import Path
import pymupdf

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "documents"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DOCUMENTS = [
    {
        "filename": "01_federated_learning_overview.pdf",
        "title": "Federated Learning: An Overview",
        "pages": [
            {
                "heading": "What is Federated Learning?",
                "body": """
Federated learning is a machine learning paradigm where a model is trained across multiple
decentralised devices or servers holding local data samples, without exchanging the raw data
itself. The central server coordinates training by aggregating model updates — typically
gradients or weight deltas — rather than raw data.

The technique was introduced by Google in 2017 to train keyboard prediction models on mobile
devices without uploading users' typed text to a central server. Since then, federated learning
has expanded into healthcare, finance, and autonomous vehicles, wherever data privacy or
regulatory constraints prevent centralised collection.

Key properties:
- Data never leaves the device or local silo.
- The global model improves iteratively via aggregation rounds.
- Participants can drop out and rejoin without halting training.
- Works with heterogeneous data distributions (non-IID).
                """,
            },
            {
                "heading": "How Federated Averaging Works",
                "body": """
The most widely used aggregation algorithm is FedAvg (Federated Averaging). Each round
proceeds as follows:

1. The server broadcasts the current global model weights to a subset of clients.
2. Each selected client trains the model locally for several epochs on its private data.
3. Clients send their updated weights back to the server.
4. The server computes a weighted average of the received weights, typically weighted by
   the number of local training samples.
5. The averaged weights become the new global model.

FedAvg reduces communication cost compared to naive gradient aggregation, because local
training already incorporates multiple gradient steps before a single round of communication.
Variants such as FedProx add a proximal term to prevent client models from drifting too far
from the global model, improving convergence under heterogeneous data distributions.
                """,
            },
            {
                "heading": "Privacy Considerations",
                "body": """
Although raw data stays local, federated learning is not inherently private. Gradient updates
can leak information about local training data through model inversion or membership inference
attacks. Two primary defences are used in practice:

Differential Privacy (DP): Gaussian or Laplacian noise is added to gradients before
transmission. The privacy budget epsilon controls the trade-off between privacy and model
utility. DP-SGD is the standard implementation.

Secure Aggregation: Cryptographic protocols allow the server to compute the sum of client
updates without seeing individual updates. Clients exchange secret keys to mask their
contributions; the masks cancel out in the aggregate, revealing only the sum.

Combining both techniques provides formal privacy guarantees while still allowing effective
model training at scale.
                """,
            },
        ],
    },
    {
        "filename": "02_vector_databases_embeddings.pdf",
        "title": "Vector Databases and Semantic Search",
        "pages": [
            {
                "heading": "Embeddings and Semantic Representations",
                "body": """
An embedding is a dense vector representation of an object — text, image, audio — in a
high-dimensional space, typically 384 to 1536 dimensions. Objects with similar meaning are
placed close together, measured by cosine similarity or Euclidean distance.

Text embeddings are produced by encoder models such as BERT, Sentence-BERT, or OpenAI's
text-embedding-ada-002. Given the sentence "The cat sat on the mat", an encoder outputs a
vector like [0.23, -0.81, 0.44, ...] that encodes its semantic content. The sentence "A
feline rested on a rug" will produce a nearby vector despite sharing no words.

This property — semantic proximity — is what makes embeddings powerful for retrieval. A
user query is embedded into the same space as stored documents, and the nearest document
vectors are returned as results.
                """,
            },
            {
                "heading": "How Vector Databases Work",
                "body": """
A vector database stores embeddings alongside metadata and provides efficient approximate
nearest-neighbour (ANN) search. Exact nearest-neighbour search in high dimensions is
prohibitively slow; ANN algorithms trade a small amount of recall for dramatically faster
query times.

Popular indexing strategies include:

HNSW (Hierarchical Navigable Small World): A graph-based index where nodes are connected
to nearby neighbours at multiple layers. Query traversal starts at a coarse layer and
refines at finer layers. Achieves very high recall with low latency. Used by ChromaDB,
Qdrant, and Weaviate.

IVF (Inverted File Index): The embedding space is partitioned into Voronoi cells via
k-means clustering. At query time, only the nearest cells are searched. Used by FAISS.

Product Quantisation (PQ): Embeddings are compressed by splitting them into sub-vectors
and quantising each independently, reducing memory footprint at the cost of some accuracy.
                """,
            },
            {
                "heading": "ChromaDB in Practice",
                "body": """
ChromaDB is an open-source embedding database optimised for AI applications. It supports
both in-memory and persistent modes, making it suitable for development and production.

A typical ChromaDB workflow:
1. Create a collection with a named embedding function.
2. Add documents: ChromaDB embeds them automatically using the configured model.
3. Query: provide a text query; ChromaDB embeds it and returns the top-k nearest documents.

ChromaDB stores raw documents, embeddings, and arbitrary metadata dictionaries. Metadata
filtering (e.g., where={"source": "report_2024.pdf"}) can be combined with semantic search
to narrow results before the ANN step.

AURA uses ChromaDB with the all-MiniLM-L6-v2 sentence transformer (384 dimensions) for
fast, CPU-friendly embeddings suitable for running entirely offline on consumer hardware.
                """,
            },
        ],
    },
    {
        "filename": "03_retrieval_augmented_generation.pdf",
        "title": "Retrieval-Augmented Generation (RAG)",
        "pages": [
            {
                "heading": "The Problem RAG Solves",
                "body": """
Large language models (LLMs) are trained on static snapshots of text. After training, their
knowledge is frozen: they cannot access documents ingested after their cut-off date, private
enterprise data, or information not represented in their training corpus.

Fine-tuning can update knowledge but is expensive, slow, and introduces the risk of
catastrophic forgetting. Prompt stuffing (pasting documents into the context window) works
for small corpora but scales poorly.

Retrieval-Augmented Generation (RAG) solves this by decoupling knowledge storage from the
model itself. A retriever fetches relevant passages from an external store at inference time;
the LLM generates an answer conditioned on both the user query and the retrieved context.
This allows the model's knowledge to be updated simply by adding documents to the store.
                """,
            },
            {
                "heading": "RAG Architecture",
                "body": """
A standard RAG pipeline has five stages:

1. Ingestion: Source documents are split into chunks (typically 500–1000 tokens with
   overlap). Each chunk is embedded and stored in a vector database.

2. Retrieval: At query time, the user's question is embedded. The top-k most similar chunks
   are retrieved using ANN search.

3. Re-ranking (optional): A cross-encoder re-ranker scores each retrieved chunk against
   the query for higher precision. More expensive than embedding similarity but more accurate.

4. Augmentation: Retrieved chunks are formatted into a prompt template alongside the query.

5. Generation: The LLM receives the augmented prompt and generates a grounded answer.
   Ideally the model cites the source chunks it used.

Evaluation metrics include faithfulness (does the answer contradict the context?),
answer relevance (does it address the question?), and context precision (are retrieved
chunks actually relevant?).
                """,
            },
            {
                "heading": "Chunking Strategies",
                "body": """
How documents are split into chunks significantly affects retrieval quality.

Fixed-size chunking: Split every N tokens with an overlap of M tokens. Simple and fast.
Overlap ensures context from the boundary of one chunk appears in the next, preventing
important content from being split across two chunks neither of which scores highly.

Recursive character splitting: Split on paragraphs first, then sentences, then words,
recursing until chunks are within the size limit. Preserves semantic units better than
fixed-size splitting.

Semantic chunking: Embed sentences and split where embedding similarity drops sharply,
grouping thematically coherent sentences together. Produces the most meaningful chunks
but is more computationally expensive.

AURA uses fixed-size chunking with 1000-token chunks and 200-token overlap by default,
configurable via MAX_CHUNK_SIZE and CHUNK_OVERLAP environment variables.
                """,
            },
        ],
    },
    {
        "filename": "04_p2p_network_architecture.pdf",
        "title": "Peer-to-Peer Network Architecture",
        "pages": [
            {
                "heading": "P2P vs Client-Server",
                "body": """
In a client-server architecture, clients send requests to a centralised server that holds
resources and processes requests. The server is a single point of failure; if it goes down,
all clients lose access. Scaling requires vertical (bigger server) or horizontal (load
balancer + server farm) growth, both of which have costs and complexity.

In a peer-to-peer (P2P) network, every node is both a client and a server. Resources are
distributed across the network; any node can serve requests to any other node. There is no
single point of failure — the network continues to function as long as some nodes are
reachable.

P2P networks are inherently more resilient and can scale without central infrastructure.
They are used in file sharing (BitTorrent), cryptocurrency (Bitcoin, Ethereum), distributed
storage (IPFS), and real-time communication (WebRTC).
                """,
            },
            {
                "heading": "Gossip Protocols",
                "body": """
Gossip protocols (also called epidemic protocols) are a family of peer-to-peer communication
patterns inspired by how rumours spread in social networks. Each node periodically selects a
random subset of peers and exchanges state with them. Information propagates exponentially
fast: after log(N) rounds, all N nodes have received a message.

Gossip protocols are used for:
- Membership management: detecting which nodes are alive or dead.
- State dissemination: spreading configuration changes or metadata.
- Pub/sub messaging: Gossipsub (used in libp2p) delivers messages to all subscribers of a
  topic within a few hops.

Key properties: decentralised, fault-tolerant, eventual consistency, low per-node overhead.
The trade-off is that gossip does not guarantee ordered delivery or exactly-once semantics.
                """,
            },
            {
                "heading": "Distributed Hash Tables",
                "body": """
A Distributed Hash Table (DHT) is a decentralised key-value store spread across many nodes.
Each node is responsible for a subset of the key space; lookups are routed through the
network in O(log N) hops.

Kademlia is the most widely deployed DHT algorithm. It uses XOR as the distance metric
between node IDs and keys. Each node maintains a routing table of buckets, each covering
nodes at a particular XOR distance. Lookups iteratively query the closest known nodes until
the target is found.

Kademlia powers BitTorrent's DHT, IPFS's content routing, and Ethereum's node discovery.
libp2p provides a Kademlia DHT implementation that AURA can leverage for decentralised
peer discovery without any central bootstrap server.
                """,
            },
        ],
    },
    {
        "filename": "05_privacy_preserving_ai.pdf",
        "title": "Privacy-Preserving AI Techniques",
        "pages": [
            {
                "heading": "Differential Privacy",
                "body": """
Differential privacy (DP) is a mathematical framework for quantifying and limiting the
privacy risk of releasing information derived from a dataset. A mechanism M satisfies
(epsilon, delta)-DP if for any two datasets D and D' differing in one record, and any
output set S:

  Pr[M(D) in S] <= exp(epsilon) * Pr[M(D') in S] + delta

Intuitively: an adversary who sees the output cannot determine with high confidence whether
any particular individual's data was included. Smaller epsilon means stronger privacy.

The Gaussian mechanism adds noise drawn from N(0, sigma^2) to numerical outputs. The noise
scale sigma is chosen based on the sensitivity of the query (how much one record can change
the output) and the desired epsilon.

DP has been adopted by Apple (iOS keyboard), Google (Chrome usage statistics), and the US
Census Bureau for publishing aggregate statistics with formal privacy guarantees.
                """,
            },
            {
                "heading": "Homomorphic Encryption",
                "body": """
Homomorphic encryption (HE) allows computation on encrypted data without decrypting it.
The result, when decrypted, equals what would have been obtained by computing on the
plaintext.

Partially homomorphic schemes support either addition or multiplication on ciphertexts.
Fully homomorphic encryption (FHE) supports both arbitrary operations but is currently
10,000x–1,000,000x slower than plaintext computation.

In federated learning, HE enables the server to aggregate encrypted client gradients. No
individual client update is ever revealed to the server; it only sees the aggregate after
decryption. This provides stronger privacy guarantees than differential privacy alone but
at higher computational cost.

CKKS (Cheon-Kim-Kim-Song) is the most practical FHE scheme for machine learning because
it natively supports floating-point arithmetic, matching the data type of neural network
gradients.
                """,
            },
            {
                "heading": "Zero-Knowledge Proofs",
                "body": """
A zero-knowledge proof (ZKP) allows a prover to convince a verifier that a statement is
true without revealing any information beyond the truth of the statement itself.

Classic example: Peggy knows the password to a cave with a magic door. Victor wants
confirmation without learning the password. Peggy enters from either side and exits from the
side Victor shouts — if she knows the password, she can always comply. After many rounds,
Victor is convinced.

In AI systems, ZKPs enable:
- Proving a model was trained on data satisfying certain criteria without revealing the data.
- Verifying that a node performed inference correctly without re-running the computation.
- Age or credential verification without disclosing the credential itself.

zk-SNARKs (Succinct Non-interactive Arguments of Knowledge) are the most practical ZKP
construction, offering constant-size proofs and fast verification. Used by Zcash and
Polygon ID.
                """,
            },
        ],
    },
    {
        "filename": "06_carbon_aware_computing.pdf",
        "title": "Carbon-Aware Computing and GreenOps",
        "pages": [
            {
                "heading": "Grid Carbon Intensity",
                "body": """
The carbon intensity of electricity measures how much CO2-equivalent is emitted per kilowatt-
hour (kWh) of electricity generated, expressed in gCO2eq/kWh. It varies by location,
time of day, and season depending on the mix of generation sources on the grid.

Typical values:
- Coal-heavy grids: 700–900 gCO2eq/kWh (e.g., Poland, South Africa)
- Average European grid: 200–400 gCO2eq/kWh
- High-renewable grids: 20–100 gCO2eq/kWh (e.g., Norway, Iceland)
- UK National Grid: fluctuates 50–350 gCO2eq/kWh depending on wind output

APIs such as Electricity Maps and the UK National Grid ESO Carbon Intensity API provide
real-time and forecast intensity data, enabling applications to make compute scheduling
decisions based on current grid conditions.
                """,
            },
            {
                "heading": "Temporal and Spatial Shifting",
                "body": """
Carbon-aware computing uses two primary strategies to reduce the emissions footprint of
workloads:

Temporal shifting: Defer non-urgent compute tasks to times when the grid is cleaner.
A machine learning training job scheduled at 2am during high wind generation emits
significantly less CO2 than the same job run at 6pm during peak demand. The task completes
the same work but with lower carbon cost.

Spatial shifting: Route workloads to data centres located in regions with lower carbon
intensity. A query that can be served from either a West European data centre or a Nordic
one should prefer the Nordic one when its grid is running on hydropower.

Both strategies require accurate carbon intensity forecasts and a scheduling layer that
understands task deadlines and priorities. Critical tasks (e.g., emergency alerts) should
never be deferred regardless of carbon intensity.
                """,
            },
            {
                "heading": "Measuring Software Carbon",
                "body": """
The Software Carbon Intensity (SCI) specification, published by the Green Software
Foundation, defines a standard formula for measuring the carbon emissions of a software
system:

  SCI = (E * I + M) / R

Where:
- E = energy consumed by the software (kWh)
- I = location-based marginal carbon intensity (gCO2eq/kWh)
- M = embodied carbon of hardware (gCO2eq), amortised over device lifetime
- R = functional unit (per query, per user, per inference)

Tools such as CodeCarbon (Python) and Cloud Carbon Footprint instrument applications to
measure E automatically using hardware performance counters or cloud provider energy APIs.

AURA's GreenOps module tracks estimated carbon per query using grid intensity data and
estimated CPU energy consumption, reporting the result via the /metrics Prometheus endpoint
and displaying it in the dashboard per-response.
                """,
            },
        ],
    },
    {
        "filename": "07_decentralised_identity.pdf",
        "title": "Decentralised Identity and Cryptographic Keys",
        "pages": [
            {
                "heading": "Decentralised Identifiers (DIDs)",
                "body": """
A Decentralised Identifier (DID) is a globally unique identifier that does not require a
centralised registry. It is controlled by its owner via a cryptographic key pair and is
resolvable to a DID Document containing public keys, authentication methods, and service
endpoints.

DID format: did:<method>:<method-specific-identifier>
Example: did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK

The did:key method derives the DID directly from a public key, making it entirely self-
contained — no blockchain or registry required. Resolution simply decodes the identifier
to recover the public key and constructs the DID Document in memory.

DIDs are the foundation of verifiable credentials: signed claims (e.g., "this entity is
over 18") issued by one DID and presented to another, verified cryptographically without
contacting the issuer.
                """,
            },
            {
                "heading": "Ed25519 Key Pairs",
                "body": """
Ed25519 is an elliptic curve digital signature algorithm using the twisted Edwards curve
Curve25519. It is the preferred signature scheme for modern identity systems due to its
properties:

- Fast: signing and verification are among the fastest of any widely deployed signature
  scheme, requiring microseconds on modern hardware.
- Small: public keys are 32 bytes, signatures are 64 bytes.
- Secure: resistant to side-channel attacks; no nonce required (unlike ECDSA).
- Deterministic: the same message and key always produce the same signature.

An Ed25519 key pair consists of a 32-byte private seed and the derived 32-byte public key.
The seed can be randomly generated or derived from a mnemonic phrase. The public key
uniquely identifies the entity; the private key signs messages that others verify using
the public key.

AURA derives each node's PeerID from its Ed25519 public key using a SHA-256 multihash,
following the libp2p peer identity specification.
                """,
            },
            {
                "heading": "Key Management and Storage",
                "body": """
Secure key management is critical: loss of a private key means loss of identity and the
ability to sign messages; compromise of a private key allows an attacker to impersonate
the owner.

Best practices:
- Store seeds encrypted at rest (AES-256-GCM with a key derived from a passphrase via
  PBKDF2 or Argon2).
- Never transmit private keys; only sign locally and transmit signatures.
- Use hardware security modules (HSMs) or secure enclaves (TPM, Apple Secure Enclave)
  for high-value keys.
- Implement key rotation: periodically generate new key pairs and publish a signed
  statement from the old key authorising the new one.

AURA persists Ed25519 seeds as hex files in the P2P_KEY_DIR directory. In production
deployments, this directory should be on an encrypted volume and access restricted to
the AURA process user.
                """,
            },
        ],
    },
    {
        "filename": "08_llm_architecture_inference.pdf",
        "title": "Large Language Models: Architecture and Local Inference",
        "pages": [
            {
                "heading": "Transformer Architecture",
                "body": """
Large language models are built on the Transformer architecture, introduced by Vaswani
et al. in 2017. A decoder-only Transformer (used by GPT, LLaMA, Mistral) processes text
autoregressively: given a sequence of tokens, it predicts the next token, appends it, and
repeats.

The core component is the self-attention mechanism, which computes a weighted sum of all
previous token representations. For each token, three vectors are computed — query, key,
and value — via learned linear projections. The attention score between two tokens is the
dot product of the query and key, scaled by the square root of the dimension and normalised
with softmax. This allows each token to attend to all previous tokens with learned weights.

Grouped Query Attention (GQA), used in LLaMA 3 and Mistral, reduces the number of key/
value heads relative to query heads, cutting the KV cache size and enabling faster inference
without significant quality loss.
                """,
            },
            {
                "heading": "Quantisation and Efficient Inference",
                "body": """
Running LLMs locally requires reducing memory footprint. A 7-billion parameter model in
float32 requires 28 GB of VRAM — exceeding consumer GPUs. Quantisation reduces the
precision of weights, dramatically lowering memory requirements:

- float16 / bfloat16: 14 GB for a 7B model. Negligible quality loss.
- int8: 7 GB. Slight quality degradation, widely used in production.
- int4 (GGUF Q4_K_M): ~4 GB. Moderate quality loss, runs on 8 GB consumer GPUs.
- int3/int2: Further reduction at the cost of more noticeable quality degradation.

GGUF is the file format used by llama.cpp and Ollama. It bundles quantised weights,
tokeniser, and model metadata in a single file. Ollama wraps llama.cpp to provide a simple
REST API, enabling any application to perform local LLM inference without GPU setup.

AURA uses Ollama with llama3.2:3b by default — a 3-billion parameter model that fits
comfortably in CPU memory while providing acceptable answer quality for RAG tasks.
                """,
            },
            {
                "heading": "RAG vs Fine-Tuning for Knowledge Updates",
                "body": """
When an LLM needs knowledge beyond its training data, two approaches are commonly compared:

Fine-tuning trains the model further on new documents, updating its weights to encode the
new knowledge. Advantages: fast inference (no retrieval step). Disadvantages: expensive,
risks catastrophic forgetting, requires retraining for every update, and provides no
citations.

RAG retrieves relevant passages at inference time and injects them into the context.
Advantages: knowledge updates by adding documents (no retraining), provenance via source
citations, works with any LLM including fully local ones. Disadvantages: adds latency
for the retrieval step, quality depends on retriever precision.

For most enterprise and local deployment scenarios, RAG is preferred because it enables
continuous knowledge updates, full data sovereignty (nothing leaves the local environment),
and verifiable answers with source citations. Fine-tuning remains useful for adapting model
behaviour (tone, format, domain vocabulary) rather than injecting factual knowledge.
                """,
            },
        ],
    },
]


def wrap(text: str, width: int = 95) -> list[str]:
    """Wrap a block of text to lines of at most `width` characters."""
    lines = []
    for paragraph in text.strip().split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            lines.append("")
        else:
            lines.extend(textwrap.wrap(paragraph, width) or [""])
    return lines


def create_pdf(doc_spec: dict) -> Path:
    out_path = OUTPUT_DIR / doc_spec["filename"]
    pdf = pymupdf.open()

    for page_spec in doc_spec["pages"]:
        page = pdf.new_page(width=595, height=842)  # A4
        y = 60

        # Document title (first page only, top)
        if page_spec is doc_spec["pages"][0]:
            page.insert_text(
                (50, y),
                doc_spec["title"],
                fontsize=18,
                fontname="helv",
                color=(0.2, 0.2, 0.8),
            )
            y += 32

        # Section heading
        page.insert_text(
            (50, y),
            page_spec["heading"],
            fontsize=13,
            fontname="helv",
            color=(0.1, 0.1, 0.1),
        )
        y += 22

        # Body text
        for line in wrap(page_spec["body"]):
            if y > 800:
                break
            page.insert_text(
                (50, y),
                line,
                fontsize=10,
                fontname="helv",
                color=(0.15, 0.15, 0.15),
            )
            y += 14

    pdf.save(str(out_path))
    pdf.close()
    return out_path


if __name__ == "__main__":
    print(f"Writing PDFs to {OUTPUT_DIR}\n")
    for doc in DOCUMENTS:
        path = create_pdf(doc)
        print(f"  Created {path.name}")
    print(f"\nDone — {len(DOCUMENTS)} documents ready.")
    print("Ingest them via the dashboard at /ingest → 'Ingest Server Directory'")
    print("or run: python -m backend.cli ingest")
