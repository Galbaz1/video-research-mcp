// Independently authored file-only Apple Vision protocol. No screen, clipboard or network input.
import Foundation
import Vision
import ImageIO

struct Options: Decodable {
    let languages: [String]
    let barcodes: Bool
    let documents: Bool
}

enum ProtocolFailure: Error { case invalidInput, excessiveOutput }

func box(_ value: CGRect) -> [Double] {
    [value.minX, value.minY, value.width, value.height]
}

func points(_ value: VNRectangleObservation) -> [[Double]] {
    [value.topLeft, value.topRight, value.bottomRight, value.bottomLeft].map {
        [Double($0.x), Double($0.y)]
    }
}

func recognize(_ image: CGImage, _ options: Options) throws -> [[String: Any]] {
    let text = VNRecognizeTextRequest()
    text.recognitionLevel = .accurate
    text.usesLanguageCorrection = false
    if options.languages.isEmpty {
        text.automaticallyDetectsLanguage = true
    } else {
        let supported = try text.supportedRecognitionLanguages()
        guard options.languages.allSatisfy({ supported.contains($0) }) else {
            throw ProtocolFailure.invalidInput
        }
        text.recognitionLanguages = options.languages
    }
    let barcode = VNDetectBarcodesRequest()
    let document = VNDetectDocumentSegmentationRequest()
    var requests: [VNRequest] = [text]
    if options.barcodes { requests.append(barcode) }
    if options.documents { requests.append(document) }
    try VNImageRequestHandler(cgImage: image, orientation: .up, options: [:]).perform(requests)
    var observations: [[String: Any]] = []
    for value in text.results ?? [] {
        guard let candidate = value.topCandidates(1).first else { continue }
        observations.append([
            "kind": "line", "text": candidate.string, "confidence": candidate.confidence,
            "raw_box": box(value.boundingBox), "raw_points": points(value)
        ])
    }
    if options.barcodes {
        for value in barcode.results ?? [] {
            observations.append([
                "kind": "barcode", "payload": value.payloadStringValue as Any? ?? NSNull(),
                "symbology": value.symbology.rawValue, "confidence": value.confidence,
                "raw_box": box(value.boundingBox), "raw_points": points(value)
            ])
        }
    }
    if options.documents {
        for value in document.results ?? [] {
            observations.append([
                "kind": "document", "confidence": value.confidence,
                "raw_box": box(value.boundingBox), "raw_points": points(value)
            ])
        }
    }
    guard observations.count <= 128 else { throw ProtocolFailure.excessiveOutput }
    return observations
}

func main() throws {
    guard CommandLine.arguments.count == 3,
          let argument = CommandLine.arguments[2].data(using: .utf8), argument.count <= 4096 else {
        throw ProtocolFailure.invalidInput
    }
    let options = try JSONDecoder().decode(Options.self, from: argument)
    let url = URL(fileURLWithPath: CommandLine.arguments[1])
    let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
    guard attributes[.type] as? FileAttributeType == .typeRegular,
          let size = attributes[.size] as? NSNumber, size.intValue <= 8 * 1024 * 1024,
          let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          CGImageSourceGetType(source) as String? == "public.png", CGImageSourceGetCount(source) == 1,
          let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
          let width = properties[kCGImagePropertyPixelWidth] as? Int,
          let height = properties[kCGImagePropertyPixelHeight] as? Int,
          width > 0, height > 0, width <= 1_000_000 / height,
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        throw ProtocolFailure.invalidInput
    }
    let result: [String: Any] = [
        "protocol": 1, "width": width, "height": height,
        "coordinate_space": "normalized_bottom_left",
        "observations": try recognize(image, options)
    ]
    let output = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
    guard output.count <= 262144 else { throw ProtocolFailure.excessiveOutput }
    FileHandle.standardOutput.write(output)
}

do { try main() } catch {
    FileHandle.standardError.write(Data("Local Vision protocol failed: \(error)\n".utf8))
    exit(1)
}
