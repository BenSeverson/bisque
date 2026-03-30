import Foundation

enum APIError: LocalizedError {
    case connectionFailed
    case unauthorized
    case serverError(statusCode: Int, message: String)
    case decodingError(Error)
    case invalidURL

    var errorDescription: String? {
        switch self {
        case .connectionFailed:
            return "Cannot connect to kiln"
        case .unauthorized:
            return "Authentication required"
        case .serverError(let code, let message):
            return "Server error \(code): \(message)"
        case .decodingError(let error):
            return "Data error: \(error.localizedDescription)"
        case .invalidURL:
            return "Invalid kiln address"
        }
    }
}
