use wgpu::util::DeviceExt;

fn main() {
    pollster::block_on(run());
}

async fn run() {
    let args: Vec<_> = std::env::args().collect();
    let padded = args.iter().any(|s| s == "--padded");
    let scalar = args.iter().any(|s| s == "--scalars");
    let array = args.iter().any(|s| s == "--array");
    let indirect = args.iter().any(|s| s == "--indirect");
    let unsigned = !args.iter().any(|s| s == "--signed" || s == "--float");
    assert!(
        !indirect || unsigned,
        "--indirect uses the u32 words as dispatch arguments"
    );
    let kind = if unsigned {
        "u32"
    } else if args.iter().any(|s| s == "--signed") {
        "i32"
    } else {
        "f32"
    };
    let source = if array {
        "@group(0) @binding(0) var<storage, read_write> counts: array<u32, 3>; @compute @workgroup_size(1) fn main() { counts = array<u32, 3>(1u, 2u, 3u); }".to_owned()
    } else if scalar {
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
        "adapter={:?}; size={size}; scalar_struct={scalar}; array={array}; indirect={indirect}; kind={kind}; validation={:?}",
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
    let mut usage = wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC;
    if indirect {
        usage |= wgpu::BufferUsages::INDIRECT;
    }
    let buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("counts"),
        contents: &bytes[..size as usize],
        usage,
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
    let expected = if kind == "f32" && !scalar && !array {
        vec![1f32.to_bits(), 2f32.to_bits(), 3f32.to_bits()]
    } else {
        vec![1, 2, 3]
    };
    assert_eq!(&values[..3], expected);
    println!("GPU readback verified: {values:08x?}");
    if indirect {
        // Use the written words as indirect dispatch arguments: 1 * 2 * 3 = 6 workgroups.
        let counter_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("workgroup_counter"),
            source: wgpu::ShaderSource::Wgsl(
                "@group(0) @binding(0) var<storage, read_write> n: atomic<u32>; @compute @workgroup_size(1) fn main() { atomicAdd(&n, 1u); }".into(),
            ),
        });
        let counter_pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("workgroup_counter"),
            layout: None,
            module: &counter_shader,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });
        let counter = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("workgroup_counter"),
            contents: &[0u8; 4],
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
        });
        let counter_readback = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("workgroup_counter_readback"),
            size: 4,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        let counter_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("workgroup_counter"),
            layout: &counter_pipeline.get_bind_group_layout(0),
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: counter.as_entire_binding(),
            }],
        });
        let mut encoder = device.create_command_encoder(&Default::default());
        {
            let mut pass = encoder.begin_compute_pass(&Default::default());
            pass.set_pipeline(&counter_pipeline);
            pass.set_bind_group(0, &counter_group, &[]);
            pass.dispatch_workgroups_indirect(&buffer, 0);
        }
        encoder.copy_buffer_to_buffer(&counter, 0, &counter_readback, 0, 4);
        queue.submit([encoder.finish()]);
        let (tx, rx) = std::sync::mpsc::channel();
        counter_readback
            .slice(..)
            .map_async(wgpu::MapMode::Read, move |result| tx.send(result).unwrap());
        device.poll(wgpu::PollType::wait_indefinitely()).unwrap();
        rx.recv().unwrap().unwrap();
        let mapped = counter_readback.slice(..).get_mapped_range().unwrap();
        let workgroups = u32::from_le_bytes(mapped[..4].try_into().unwrap());
        assert_eq!(workgroups, 6, "indirect dispatch workgroup count");
        println!("Indirect dispatch verified: {workgroups} workgroups");
    }
}
