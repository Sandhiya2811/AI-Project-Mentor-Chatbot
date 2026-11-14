# Deep learning, LLMs and RAG

## Neural network basics
A neural network stacks layers of weighted sums and non-linear activations. Training repeats: forward pass, loss calculation, backpropagation, weight update by an optimiser. Important knobs: learning rate, batch size, epochs, network size. Watch training versus validation loss to detect overfitting. Frameworks: PyTorch, TensorFlow/Keras.

## Large language models
LLMs predict the next token and are steered with prompts. Good prompts state the role, task, constraints and output format. Temperature controls randomness. Models can hallucinate, so ground answers in retrieved sources and validate outputs. Never send secrets in prompts; keep API keys in environment variables.

## Retrieval-Augmented Generation (RAG)
RAG improves answers by retrieving relevant text and adding it to the prompt. Steps: split documents into chunks, create embeddings, store them in a vector index (FAISS or ChromaDB), embed the user question, retrieve the nearest chunks, build a prompt with those chunks, and generate an answer that cites them. Quality depends on chunk size, embedding model and retrieval settings. Evaluate retrieval separately from generation.

## Speech and voice assistants
A voice assistant chains speech-to-text, intent understanding, an action or answer step, and text-to-speech. Each stage can fail independently, so log intermediate results. Handle noise, silence and unknown commands gracefully.
