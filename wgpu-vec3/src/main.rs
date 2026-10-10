use wgpu::util::DeviceExt;

fn main() {
    pollster::block_on(run());
}

async fn run() {
    let args: Vec<_> = std::env::args().collect();
    let padded = args.iter().any(|s| s == "--padded");
    let scalar = args.iter().any(|s| s == "--scalars");
    let unsigned = !args.iter().any(|s| s == "--signed" || s == "--float");
    let kind = if unsigned {
        "u32"
    } else if args.iter().any(|s| s == "--signed") {
        "i32"
    } else {
        "f32"
    };
    let source = if scalar {
        "struct Counts { x: u32, y: u32, z: u32 }; @group(0) @binding(0) var<storage, read_write> counts: Counts; @compute @workgroup_size(1) fn main() { counts = Counts(1u, 2u, 3u); }".to_owned()
    } else {
        format!(
            "@group(0) @binding(0) var<storage, read_write> counts: vec3<{kind}>; @compute @workgroup_size(1) fn main() {{ counts = vec3<{kind}>(1, 2, 3); }}"
        )
    };
    if let Some(index) = args.iter().position(|s| s == "--msl") {
        let path = args.get(index + 1).expect("--msl needs an output file");
        let module = naga::front::wgsl::parse_str(&source).unwrap();
        let info = naga::valid::Validator::new(
            naga::valid::ValidationFlags::all(),
            naga::valid::Capabilities::all(),
        )
        .validate(&module)
        .unwrap();
        let options = naga::back::msl::Options {
            fake_missing_bindings: true,
            ..Default::default()
        };
        let (msl, _) =
            naga::back::msl::write_string(&module, &info, &options, &Default::default()).unwrap();
        std::fs::write(path, msl).unwrap();
        println!("MSL translation written");
        if args.iter().any(|s| s == "--translate-only") {
            return;
        }
    }
    let size = if padded { 16 } else { 12 };
    let instance = wgpu::Instance::new(wgpu::InstanceDescriptor {
        backends: if cfg!(target_os = "macos") {
            wgpu::Backends::METAL
        } else {
            wgpu::Backends::VULKAN
        },
        ..wgpu::InstanceDescriptor::new_without_display_handle()
    });
    let adapter = instance.request_adapter(&Default::default()).await.unwrap();
    println!(
        "adapter={:?}; size={size}; scalar_struct={scalar}; kind={kind}; validation={:?}",
        adapter.get_info(),
        std::env::var("MTL_DEBUG_LAYER")
    );
    let (device, queue) = adapter.request_device(&Default::default()).await.unwrap();
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("vec3_storage"),
        source: wgpu::ShaderSource::Wgsl(source.into()),
    });
    let pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
        label: Some("vec3_storage"),
        layout: None,
        module: &shader,
        entry_point: Some("main"),
        compilation_options: Default::default(),
        cache: None,
    });
    let initial = [0u32, 0, 0, 0xdeadbeef];
    let bytes: Vec<_> = initial.into_iter().flat_map(u32::to_le_bytes).collect();
    let buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("counts"),
        contents: &bytes[..size as usize],
        usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
    });
    let readback = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("readback"),
        size,
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });
    let layout = pipeline.get_bind_group_layout(0);
    let group = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("counts"),
        layout: &layout,
        entries: &[wgpu::BindGroupEntry {
            binding: 0,
            resource: buffer.as_entire_binding(),
        }],
    });
    let mut encoder = device.create_command_encoder(&Default::default());
    {
        let mut pass = encoder.begin_compute_pass(&Default::default());
        pass.set_pipeline(&pipeline);
        pass.set_bind_group(0, &group, &[]);
        pass.dispatch_workgroups(1, 1, 1);
    }
    encoder.copy_buffer_to_buffer(&buffer, 0, &readback, 0, size);
    queue.submit([encoder.finish()]);
    let (tx, rx) = std::sync::mpsc::channel();
    readback
        .slice(..)
        .map_async(wgpu::MapMode::Read, move |result| tx.send(result).unwrap());
    device.poll(wgpu::PollType::wait_indefinitely()).unwrap();
    rx.recv().unwrap().unwrap();
    let mapped = readback.slice(..).get_mapped_range().unwrap();
    let values: Vec<_> = mapped
        .as_chunks::<4>()
        .0
        .iter()
        .copied()
        .map(u32::from_le_bytes)
        .collect();
    let expected = if kind == "f32" && !scalar {
        vec![1f32.to_bits(), 2f32.to_bits(), 3f32.to_bits()]
    } else {
        vec![1, 2, 3]
    };
    assert_eq!(&values[..3], expected);
    println!("GPU readback verified: {values:08x?}");
}
