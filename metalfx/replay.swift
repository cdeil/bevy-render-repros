// Offline replay of original procedural HDR/surface buffers through Apple's denoiser.
// This proves native GPU execution, not Bevy/wgpu integration or moving-worker support.
// xcrun swift replay.swift <guide folder> <new output folder> [--reset-every-frame | --no-cut-reset]
import Foundation
import Metal
import MetalFX
import simd

// --reset-every-frame: control without history. --no-cut-reset: keep history across the
// frame-16 object teleport, to compare against the explicit reset there.
guard CommandLine.arguments.count == 3 || CommandLine.arguments.count == 4 else { fatalError("Usage: replay.swift <guides> <new output> [--reset-every-frame | --no-cut-reset]") }
let flag = CommandLine.arguments.count == 4 ? CommandLine.arguments[3] : nil
guard flag == nil || flag == "--reset-every-frame" || flag == "--no-cut-reset" else { fatalError("Unknown flag") }
let resetEveryFrame = flag == "--reset-every-frame"
let cutReset = flag != "--no-cut-reset"
let input = URL(fileURLWithPath: CommandLine.arguments[1])
let output = URL(fileURLWithPath: CommandLine.arguments[2])
guard !FileManager.default.fileExists(atPath: output.path) else { fatalError("Use a new output folder") }
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
let files = try FileManager.default.contentsOfDirectory(at: input, includingPropertiesForKeys: nil)
    .filter { $0.pathExtension == "json" }.sorted { $0.lastPathComponent < $1.lastPathComponent }
guard let first = files.first, let device = MTLCreateSystemDefaultDevice(),
      MTLFXTemporalDenoisedScalerDescriptor.supportsDevice(device), let queue = device.makeCommandQueue()
else { fatalError("Missing guides or MetalFX denoising support") }
struct GuideMeta: Decodable {
    let width: Int, height: Int
    let jitter: [Double], world_to_view: [Double], view_to_clip: [Double]
    let reset_history: Bool
}
let firstMeta = try JSONDecoder().decode(GuideMeta.self, from: Data(contentsOf: first))
let width = firstMeta.width, height = firstMeta.height
let descriptor = MTLFXTemporalDenoisedScalerDescriptor()
descriptor.inputWidth = width; descriptor.inputHeight = height
descriptor.outputWidth = width; descriptor.outputHeight = height
descriptor.colorTextureFormat = .rgba16Float; descriptor.outputTextureFormat = .rgba16Float
descriptor.depthTextureFormat = .r32Float; descriptor.motionTextureFormat = .rg16Float
descriptor.diffuseAlbedoTextureFormat = .rgba8Unorm; descriptor.specularAlbedoTextureFormat = .rgba8Unorm
descriptor.normalTextureFormat = .rgba16Float; descriptor.roughnessTextureFormat = .r16Float
descriptor.requiresSynchronousInitialization = true
let initialization = Date()
guard let scaler = descriptor.makeTemporalDenoisedScaler(device: device) else { fatalError("Scaler creation failed") }
let initSeconds = Date().timeIntervalSince(initialization)

func texture(_ format: MTLPixelFormat, _ usage: MTLTextureUsage, _ privateStorage: Bool = false, _ w: Int? = nil, _ h: Int? = nil) -> MTLTexture {
    let d = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: format, width: w ?? width, height: h ?? height, mipmapped: false)
    d.storageMode = privateStorage ? .private : .shared; d.usage = usage
    return device.makeTexture(descriptor: d)!
}
let color = texture(.rgba16Float, scaler.colorTextureUsage)
let depth = texture(.r32Float, scaler.depthTextureUsage)
let motion = texture(.rg16Float, scaler.motionTextureUsage)
let diffuse = texture(.rgba8Unorm, scaler.diffuseAlbedoTextureUsage)
let specular = texture(.rgba8Unorm, scaler.specularAlbedoTextureUsage)
let normal = texture(.rgba16Float, scaler.normalTextureUsage)
let roughness = texture(.r16Float, scaler.roughnessTextureUsage)
let result = texture(.rgba16Float, scaler.outputTextureUsage, true)
let exposure = texture(.r16Float, .shaderRead, false, 1, 1)
var one = Float16(1)
withUnsafeBytes(of: &one) { exposure.replace(region: MTLRegionMake2D(0, 0, 1, 1), mipmapLevel: 0, withBytes: $0.baseAddress!, bytesPerRow: 2) }
scaler.colorTexture = color; scaler.depthTexture = depth; scaler.motionTexture = motion
scaler.diffuseAlbedoTexture = diffuse; scaler.specularAlbedoTexture = specular
scaler.normalTexture = normal; scaler.roughnessTexture = roughness; scaler.outputTexture = result
scaler.exposureTexture = exposure; scaler.preExposure = 1; scaler.isDepthReversed = true
scaler.motionVectorScaleX = -Float(width); scaler.motionVectorScaleY = -Float(height)
let readback = device.makeBuffer(length: width * height * 8, options: .storageModeShared)!
var gpuSeconds: [Double] = []
var wallSeconds: [Double] = []

func upload<T>(_ values: [T], to texture: MTLTexture, channels: Int) {
    values.withUnsafeBytes { texture.replace(region: MTLRegionMake2D(0, 0, width, height), mipmapLevel: 0, withBytes: $0.baseAddress!, bytesPerRow: width * channels * MemoryLayout<T>.stride) }
}
func matrix(_ numbers: [Float]) -> simd_float4x4 {
    simd_float4x4(columns: (SIMD4(numbers[0...3]), SIMD4(numbers[4...7]), SIMD4(numbers[8...11]), SIMD4(numbers[12...15])))
}
func pfm(_ rgb: [Float], _ url: URL) throws {
    var data = Data("PF\n\(width) \(height)\n-1.0\n".utf8)
    for row in (0..<height).reversed() {
        let pixels = Array(rgb[(row * width * 3)..<((row + 1) * width * 3)])
        pixels.withUnsafeBytes { data.append(contentsOf: $0) }
    }
    try data.write(to: url)
}

for (index, file) in files.enumerated() {
    try autoreleasepool {
        let meta = try JSONDecoder().decode(GuideMeta.self, from: Data(contentsOf: file))
        guard meta.width == width && meta.height == height else { fatalError("Guide dimensions changed") }
        let data = try Data(contentsOf: file.deletingPathExtension().appendingPathExtension("bin"))
        guard data.count == width * height * 6 * 16 else { fatalError("Guide data length mismatch") }
        let packed: [Float] = data.withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
        var c = [Float16](), d = [Float](), m = [Float16](), a = [UInt8](), s = [UInt8](), n = [Float16](), r = [Float16](), raw = [Float]()
        for pixel in 0..<(width * height) {
            let k = pixel * 24
            c.append(contentsOf: packed[k..<(k+4)].map(Float16.init))
            raw.append(contentsOf: packed[k..<(k+3)])
            d.append(packed[k+4]); m.append(contentsOf: packed[(k+8)..<(k+10)].map(Float16.init))
            for channel in 0..<4 {
                a.append(UInt8((max(0, min(1, packed[k+12+channel])) * 255).rounded()))
                s.append(UInt8((max(0, min(1, packed[k+16+channel])) * 255).rounded()))
                n.append(Float16(packed[k+20+channel]))
            }
            // The fixture exports perceptual roughness; MetalFX expects linear roughness.
            // Convention documented in Apple's WWDC25 session 211 (no code copied).
            r.append(Float16(packed[k+23] * packed[k+23]))
        }
        upload(c, to: color, channels: 4); upload(d, to: depth, channels: 1)
        upload(m, to: motion, channels: 2); upload(a, to: diffuse, channels: 4)
        upload(s, to: specular, channels: 4); upload(n, to: normal, channels: 4); upload(r, to: roughness, channels: 1)
        let jitter = meta.jitter.map(Float.init)
        scaler.jitterOffsetX = -jitter[0]; scaler.jitterOffsetY = -jitter[1]
        scaler.worldToViewMatrix = matrix(meta.world_to_view.map(Float.init))
        scaler.viewToClipMatrix = matrix(meta.view_to_clip.map(Float.init))
        scaler.shouldResetHistory = index == 0 || (meta.reset_history && cutReset) || resetEveryFrame
        let started = Date()
        let command = queue.makeCommandBuffer()!
        scaler.encode(commandBuffer: command)
        let blit = command.makeBlitCommandEncoder()!
        blit.copy(from: result, sourceSlice: 0, sourceLevel: 0, sourceOrigin: MTLOrigin(x: 0, y: 0, z: 0), sourceSize: MTLSize(width: width, height: height, depth: 1), to: readback, destinationOffset: 0, destinationBytesPerRow: width * 8, destinationBytesPerImage: width * height * 8)
        blit.endEncoding(); command.commit(); command.waitUntilCompleted()
        guard command.status == .completed else { fatalError("Metal command failed: \(String(describing: command.error))") }
        gpuSeconds.append(command.gpuEndTime - command.gpuStartTime)
        wallSeconds.append(Date().timeIntervalSince(started))
        let halves = readback.contents().bindMemory(to: Float16.self, capacity: width * height * 4)
        var clean = [Float]()
        for pixel in 0..<(width * height) { for channel in 0..<3 { clean.append(Float(halves[pixel*4+channel])) } }
        guard clean.allSatisfy({ $0.isFinite }) else { fatalError("Nonfinite MetalFX output") }
        let name = file.deletingPathExtension().lastPathComponent
        try pfm(raw, output.appendingPathComponent("\(name)-raw.pfm"))
        try pfm(clean, output.appendingPathComponent("\(name)-metalfx.pfm"))
    }
}
let report: [String: Any] = [
    "device": device.name, "api": "MTLFXTemporalDenoisedScaler", "frames": files.count,
    "width": width, "height": height, "initialization_s": initSeconds,
    "gpu_seconds": gpuSeconds, "encode_wait_seconds": wallSeconds,
    "roughness_mapping": "Fixture perceptual roughness squared to linear roughness",
    "motion_mapping": "Unjittered UV displacement, negated and scaled to pixels",
    "history": resetEveryFrame ? "Reset every frame (no-history control)"
        : cutReset ? "Reset at first frame and at the frame-16 object teleport"
        : "Reset at first frame only; history kept across the frame-16 object teleport",
    "reset_every_frame": resetEveryFrame, "teleport_reset": cutReset,
    // Requested only; the analysis checks the runtime's own log line.
    "metal_api_validation_requested": ProcessInfo.processInfo.environment["MTL_DEBUG_LAYER"] == "1",
    "os": ProcessInfo.processInfo.operatingSystemVersionString,
    "scope": "Offline replay of original procedural buffers, native resolution, actual completed Metal commands. GPU timings include output readback. Not a live Bevy integration or a cross-host renderer benchmark.",
]
try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: output.appendingPathComponent("report.json"))
print("Completed \(files.count) frames on \(device.name); output \(output.path)")
