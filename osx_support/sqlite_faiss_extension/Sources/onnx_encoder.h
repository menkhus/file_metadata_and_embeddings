/*
 * onnx_encoder.h
 * ONNX Runtime wrapper for text encoding
 */

#ifndef ONNX_ENCODER_H
#define ONNX_ENCODER_H

#include <string>
#include <vector>

class ONNXEncoder {
public:
    ONNXEncoder();
    ~ONNXEncoder();
    
    // Initialize encoder with model
    bool initialize(const std::string& model_path = "");
    
    // Encode text to embedding vector
    std::vector<float> encode(const std::string& text);
    
    // Get embedding dimension
    int dimension() const { return dimension_; }
    
private:
    void* session_;  // Ort::Session*
    void* env_;      // Ort::Env*
    int dimension_;
    
    // Tokenize text (simple whitespace tokenizer for now)
    std::vector<int64_t> tokenize(const std::string& text);
};

#endif // ONNX_ENCODER_H
