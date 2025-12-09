/*
 * faiss_extension.cpp
 * SQLite extension for FAISS-based semantic search
 * 
 * Provides SQL functions:
 * - faiss_build_index() - Build FAISS index from embeddings
 * - faiss_search(query, top_k) - Semantic search
 * - faiss_search_vector(embedding_blob, top_k) - Search with pre-computed embedding
 * - faiss_index_stats() - Get index statistics
 * - faiss_encode_text(text) - Encode text to embedding
 */

#include <sqlite3ext.h>
SQLITE_EXTENSION_INIT1

#include <faiss/IndexFlat.h>
#include <faiss/IndexIVFFlat.h>
#include <vector>
#include <string>
#include <memory>
#include <cstring>
#include "onnx_encoder.h"

// Global state
static std::unique_ptr<faiss::Index> g_index;
static std::vector<int64_t> g_chunk_ids;
static std::unique_ptr<ONNXEncoder> g_encoder;
static int g_dimension = 384; // all-MiniLM-L6-v2 dimension

/*
 * faiss_build_index()
 * 
 * Builds FAISS index from embeddings in text_chunks_v2 table
 * Returns JSON: {"status":"success","vectors_loaded":N,"dimension":D}
 */
static void faiss_build_index_func(
    sqlite3_context *context,
    int argc,
    sqlite3_value **argv
) {
    sqlite3 *db = sqlite3_context_db_handle(context);
    
    // Query embeddings from database
    const char *sql = 
        "SELECT id, embedding FROM text_chunks_v2 "
        "WHERE embedding IS NOT NULL "
        "ORDER BY id";
    
    sqlite3_stmt *stmt;
    int rc = sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        sqlite3_result_error(context, "Failed to prepare query", -1);
        return;
    }
    
    std::vector<float> vectors;
    std::vector<int64_t> chunk_ids;
    
    while ((rc = sqlite3_step(stmt)) == SQLITE_ROW) {
        int64_t id = sqlite3_column_int64(stmt, 0);
        const void *blob = sqlite3_column_blob(stmt, 1);
        int blob_size = sqlite3_column_bytes(stmt, 1);
        
        if (blob && blob_size == g_dimension * sizeof(float)) {
            const float *embedding = static_cast<const float*>(blob);
            vectors.insert(vectors.end(), embedding, embedding + g_dimension);
            chunk_ids.push_back(id);
        }
    }
    
    sqlite3_finalize(stmt);
    
    if (vectors.empty()) {
        sqlite3_result_text(context, 
            "{\"status\":\"error\",\"message\":\"No embeddings found\"}", 
            -1, SQLITE_TRANSIENT);
        return;
    }
    
    // Build FAISS index
    int n_vectors = chunk_ids.size();
    g_index = std::make_unique<faiss::IndexFlatL2>(g_dimension);
    g_index->add(n_vectors, vectors.data());
    g_chunk_ids = std::move(chunk_ids);
    
    // Return success JSON
    char result[256];
    snprintf(result, sizeof(result),
        "{\"status\":\"success\",\"vectors_loaded\":%d,\"dimension\":%d,\"index_type\":\"IndexFlatL2\"}",
        n_vectors, g_dimension);
    
    sqlite3_result_text(context, result, -1, SQLITE_TRANSIENT);
}

/*
 * faiss_search(query_text, top_k)
 * 
 * Semantic search using text query
 * Returns table with columns: rank, chunk_id, distance, similarity_score
 */
static void faiss_search_func(
    sqlite3_context *context,
    int argc,
    sqlite3_value **argv
) {
    if (argc < 1) {
        sqlite3_result_error(context, "Usage: faiss_search(query, [top_k])", -1);
        return;
    }
    
    if (!g_index) {
        sqlite3_result_error(context, "Index not built. Call faiss_build_index() first", -1);
        return;
    }
    
    if (!g_encoder) {
        // Initialize encoder on first use
        g_encoder = std::make_unique<ONNXEncoder>();
        if (!g_encoder->initialize()) {
            sqlite3_result_error(context, "Failed to initialize encoder", -1);
            return;
        }
    }
    
    const char *query = reinterpret_cast<const char*>(sqlite3_value_text(argv[0]));
    int top_k = (argc > 1) ? sqlite3_value_int(argv[1]) : 5;
    
    // Encode query
    std::vector<float> query_embedding = g_encoder->encode(query);
    if (query_embedding.empty()) {
        sqlite3_result_error(context, "Failed to encode query", -1);
        return;
    }
    
    // Search FAISS index
    std::vector<float> distances(top_k);
    std::vector<faiss::idx_t> indices(top_k);
    
    g_index->search(1, query_embedding.data(), top_k, 
                    distances.data(), indices.data());
    
    // TODO: Return results as virtual table
    // For now, return JSON array
    std::string result = "[";
    for (int i = 0; i < top_k && indices[i] >= 0; i++) {
        if (i > 0) result += ",";
        
        int64_t chunk_id = g_chunk_ids[indices[i]];
        float distance = distances[i];
        float similarity = 1.0f / (1.0f + distance);
        
        char item[256];
        snprintf(item, sizeof(item),
            "{\"rank\":%d,\"chunk_id\":%lld,\"distance\":%.4f,\"similarity_score\":%.4f}",
            i + 1, chunk_id, distance, similarity);
        result += item;
    }
    result += "]";
    
    sqlite3_result_text(context, result.c_str(), -1, SQLITE_TRANSIENT);
}

/*
 * faiss_search_vector(embedding_blob, top_k)
 * 
 * Search using pre-computed embedding
 */
static void faiss_search_vector_func(
    sqlite3_context *context,
    int argc,
    sqlite3_value **argv
) {
    if (argc < 1) {
        sqlite3_result_error(context, "Usage: faiss_search_vector(embedding, [top_k])", -1);
        return;
    }
    
    if (!g_index) {
        sqlite3_result_error(context, "Index not built. Call faiss_build_index() first", -1);
        return;
    }
    
    const void *blob = sqlite3_value_blob(argv[0]);
    int blob_size = sqlite3_value_bytes(argv[0]);
    int top_k = (argc > 1) ? sqlite3_value_int(argv[1]) : 5;
    
    if (!blob || blob_size != g_dimension * sizeof(float)) {
        sqlite3_result_error(context, "Invalid embedding size", -1);
        return;
    }
    
    const float *query_embedding = static_cast<const float*>(blob);
    
    // Search FAISS index
    std::vector<float> distances(top_k);
    std::vector<faiss::idx_t> indices(top_k);
    
    g_index->search(1, query_embedding, top_k, 
                    distances.data(), indices.data());
    
    // Return JSON array
    std::string result = "[";
    for (int i = 0; i < top_k && indices[i] >= 0; i++) {
        if (i > 0) result += ",";
        
        int64_t chunk_id = g_chunk_ids[indices[i]];
        float distance = distances[i];
        float similarity = 1.0f / (1.0f + distance);
        
        char item[256];
        snprintf(item, sizeof(item),
            "{\"rank\":%d,\"chunk_id\":%lld,\"distance\":%.4f,\"similarity_score\":%.4f}",
            i + 1, chunk_id, distance, similarity);
        result += item;
    }
    result += "]";
    
    sqlite3_result_text(context, result.c_str(), -1, SQLITE_TRANSIENT);
}

/*
 * faiss_index_stats()
 * 
 * Returns JSON with index statistics
 */
static void faiss_index_stats_func(
    sqlite3_context *context,
    int argc,
    sqlite3_value **argv
) {
    if (!g_index) {
        sqlite3_result_text(context, 
            "{\"status\":\"not_built\",\"message\":\"Index not built yet\"}", 
            -1, SQLITE_TRANSIENT);
        return;
    }
    
    int n_vectors = g_index->ntotal;
    float memory_mb = (n_vectors * g_dimension * sizeof(float)) / (1024.0f * 1024.0f);
    
    char result[256];
    snprintf(result, sizeof(result),
        "{\"vectors\":%d,\"dimension\":%d,\"index_type\":\"IndexFlatL2\",\"memory_mb\":%.2f}",
        n_vectors, g_dimension, memory_mb);
    
    sqlite3_result_text(context, result, -1, SQLITE_TRANSIENT);
}

/*
 * faiss_encode_text(text)
 * 
 * Encode text to embedding vector (returns BLOB)
 */
static void faiss_encode_text_func(
    sqlite3_context *context,
    int argc,
    sqlite3_value **argv
) {
    if (argc < 1) {
        sqlite3_result_error(context, "Usage: faiss_encode_text(text)", -1);
        return;
    }
    
    if (!g_encoder) {
        g_encoder = std::make_unique<ONNXEncoder>();
        if (!g_encoder->initialize()) {
            sqlite3_result_error(context, "Failed to initialize encoder", -1);
            return;
        }
    }
    
    const char *text = reinterpret_cast<const char*>(sqlite3_value_text(argv[0]));
    std::vector<float> embedding = g_encoder->encode(text);
    
    if (embedding.empty()) {
        sqlite3_result_error(context, "Failed to encode text", -1);
        return;
    }
    
    sqlite3_result_blob(context, embedding.data(), 
                       embedding.size() * sizeof(float), 
                       SQLITE_TRANSIENT);
}

/*
 * Extension entry point
 */
#ifdef _WIN32
__declspec(dllexport)
#endif
int sqlite3_faissextension_init(
    sqlite3 *db,
    char **pzErrMsg,
    const sqlite3_api_routines *pApi
) {
    SQLITE_EXTENSION_INIT2(pApi);
    
    int rc;
    
    // Register functions
    rc = sqlite3_create_function(db, "faiss_build_index", 0, 
                                 SQLITE_UTF8, nullptr,
                                 faiss_build_index_func, nullptr, nullptr);
    if (rc != SQLITE_OK) return rc;
    
    rc = sqlite3_create_function(db, "faiss_search", -1,
                                 SQLITE_UTF8, nullptr,
                                 faiss_search_func, nullptr, nullptr);
    if (rc != SQLITE_OK) return rc;
    
    rc = sqlite3_create_function(db, "faiss_search_vector", -1,
                                 SQLITE_UTF8, nullptr,
                                 faiss_search_vector_func, nullptr, nullptr);
    if (rc != SQLITE_OK) return rc;
    
    rc = sqlite3_create_function(db, "faiss_index_stats", 0,
                                 SQLITE_UTF8, nullptr,
                                 faiss_index_stats_func, nullptr, nullptr);
    if (rc != SQLITE_OK) return rc;
    
    rc = sqlite3_create_function(db, "faiss_encode_text", 1,
                                 SQLITE_UTF8, nullptr,
                                 faiss_encode_text_func, nullptr, nullptr);
    if (rc != SQLITE_OK) return rc;
    
    return SQLITE_OK;
}
