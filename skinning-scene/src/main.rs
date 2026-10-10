use bevy::{
    camera::{CameraMainTextureUsages, Exposure, Hdr, RenderTarget, visibility::NoFrustumCulling},
    core_pipeline::tonemapping::{DebandDither, Tonemapping},
    mesh::{
        Indices, VertexAttributeValues,
        morph::{MeshMorphWeights, MorphAttributes},
        skinning::{SkinnedMesh, SkinnedMeshInverseBindposes},
    },
    prelude::*,
    render::{
        pipelined_rendering::PipelinedRenderingPlugin,
        render_resource::{TextureFormat, TextureUsages},
        view::window::screenshot::{Screenshot, save_to_disk},
    },
    solari::{
        pathtracer::{Pathtracer, PathtracingPlugin},
        prelude::{RaytracingMesh3d, SolariPlugins},
    },
    window::ExitCondition,
};
#[derive(Resource)]
struct Settings {
    mode: String,
    angle: f32,
    ray: bool,
}
#[derive(Resource)]
struct Target(Handle<Image>);
fn main() {
    let args: Vec<_> = std::env::args().collect();
    let mode = args
        .get(1)
        .expect("<mode> <angle> <new.png> [--ray]")
        .clone();
    // extra-attr: unskinned mesh with one extra COLOR attribute.
    // morph: exactly the four attributes plus a morph target equal to the baked pose.
    // bind-copy-offset: bind-pose ray copy on a skinned entity translated by +1 x.
    assert!(matches!(
        mode.as_str(),
        "native" | "bind-copy" | "baked" | "extra-attr" | "morph" | "bind-copy-offset"
    ));
    let angle = args.get(2).expect("angle radians").parse().unwrap();
    let output = args.get(3).expect("new output").clone();
    let ray = args.iter().any(|s| s == "--ray");
    assert!(!std::path::Path::new(&output).exists());
    let mut app = App::new();
    app.add_plugins(
        DefaultPlugins
            .set(bevy::render::RenderPlugin {
                synchronous_pipeline_compilation: true,
                ..default()
            })
            .set(WindowPlugin {
                primary_window: None,
                exit_condition: ExitCondition::DontExit,
                ..default()
            })
            .disable::<PipelinedRenderingPlugin>(),
    )
    .insert_resource(Settings { mode, angle, ray })
    .add_systems(Startup, setup);
    if ray {
        app.add_plugins((SolariPlugins, PathtracingPlugin));
    }
    app.finish();
    app.cleanup();
    for frame in 0..200 {
        app.update();
        if frame == 140 {
            let target = app.world().resource::<Target>().0.clone();
            app.world_mut()
                .spawn(Screenshot::image(target))
                .observe(save_to_disk(output.clone()));
        }
        std::thread::sleep(std::time::Duration::from_millis(5));
    }
    assert!(std::path::Path::new(&output).exists());
    println!("Completed 200 updates and screenshot readback; ray={ray}");
}
fn setup(
    mut commands: Commands,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<StandardMaterial>>,
    mut images: ResMut<Assets<Image>>,
    mut poses: ResMut<Assets<SkinnedMeshInverseBindposes>>,
    settings: Res<Settings>,
) {
    let mut image = Image::new_target_texture(384, 384, TextureFormat::Rgba8UnormSrgb, None);
    image.texture_descriptor.usage |= TextureUsages::COPY_SRC;
    let target = images.add(image);
    commands.insert_resource(Target(target.clone()));
    let mut camera = commands.spawn((
        Camera3d::default(),
        Camera {
            clear_color: ClearColorConfig::Custom(Color::BLACK),
            ..default()
        },
        RenderTarget::Image(target.into()),
        Transform::from_xyz(0.0, 0.0, 4.0).looking_at(Vec3::ZERO, Vec3::Y),
        Hdr,
        Msaa::Off,
        Tonemapping::None,
        DebandDither::Disabled,
        Exposure { ev100: 0.0 },
    ));
    if settings.ray {
        camera.insert((
            Pathtracer::default(),
            CameraMainTextureUsages::default().with(TextureUsages::STORAGE_BINDING),
        ));
    }
    let mut base = Mesh::from(Cuboid::new(0.4, 1.6, 0.2));
    base.generate_tangents().unwrap();
    if let Some(Indices::U16(indices)) = base.indices() {
        base.insert_indices(Indices::U32(
            indices.iter().map(|&i| u32::from(i)).collect(),
        ));
    }
    let upper = match base.attribute(Mesh::ATTRIBUTE_POSITION).unwrap() {
        VertexAttributeValues::Float32x3(values) => {
            values.iter().map(|v| v[1] > 0.0).collect::<Vec<_>>()
        }
        _ => unreachable!(),
    };
    let rotation = Quat::from_rotation_z(settings.angle);
    let mut skin = base.clone();
    skin.insert_attribute(
        Mesh::ATTRIBUTE_JOINT_INDEX,
        VertexAttributeValues::Uint16x4(upper.iter().map(|&u| [u16::from(u), 0, 0, 0]).collect()),
    );
    skin.insert_attribute(
        Mesh::ATTRIBUTE_JOINT_WEIGHT,
        vec![[1.0, 0.0, 0.0, 0.0]; upper.len()],
    );
    let mut baked = base.clone();
    for attribute in [Mesh::ATTRIBUTE_POSITION, Mesh::ATTRIBUTE_NORMAL] {
        if let Some(VertexAttributeValues::Float32x3(values)) = baked.attribute_mut(attribute) {
            for (value, &u) in values.iter_mut().zip(&upper) {
                if u {
                    *value = (rotation * Vec3::from_array(*value)).to_array();
                }
            }
        }
    }
    if let Some(VertexAttributeValues::Float32x4(values)) =
        baked.attribute_mut(Mesh::ATTRIBUTE_TANGENT)
    {
        for (value, &u) in values.iter_mut().zip(&upper) {
            if u {
                let xyz = rotation * Vec3::new(value[0], value[1], value[2]);
                value[..3].copy_from_slice(&xyz.to_array());
            }
        }
    }
    let mut extra = base.clone();
    extra.insert_attribute(Mesh::ATTRIBUTE_COLOR, vec![[1.0f32; 4]; upper.len()]);
    let mut morph = base.clone();
    let (
        Some(VertexAttributeValues::Float32x3(positions)),
        Some(VertexAttributeValues::Float32x3(normals)),
    ) = (
        base.attribute(Mesh::ATTRIBUTE_POSITION),
        base.attribute(Mesh::ATTRIBUTE_NORMAL),
    )
    else {
        unreachable!()
    };
    // One morph target whose full weight reproduces the baked pose; tangents unchanged.
    morph.set_morph_targets(
        positions
            .iter()
            .zip(normals)
            .zip(&upper)
            .map(|((p, n), &u)| {
                let (p, n) = (Vec3::from_array(*p), Vec3::from_array(*n));
                if u {
                    MorphAttributes::new(rotation * p - p, rotation * n - n, Vec3::ZERO)
                } else {
                    MorphAttributes::new(Vec3::ZERO, Vec3::ZERO, Vec3::ZERO)
                }
            })
            .collect(),
    );
    let (raster, ray_mesh) = match settings.mode.as_str() {
        "native" => {
            let handle = meshes.add(skin);
            (handle.clone(), handle)
        }
        "bind-copy" | "bind-copy-offset" => (meshes.add(skin), meshes.add(base)),
        "extra-attr" => {
            let handle = meshes.add(extra);
            (handle.clone(), handle)
        }
        "morph" => {
            let handle = meshes.add(morph);
            (handle.clone(), handle)
        }
        "baked" => {
            let handle = meshes.add(baked);
            (handle.clone(), handle)
        }
        _ => unreachable!(),
    };
    let entity = commands
        .spawn((
            Mesh3d(raster),
            MeshMaterial3d(materials.add(StandardMaterial {
                unlit: true,
                base_color: Color::srgb_u8(200, 20, 20),
                emissive: LinearRgba::new(0.5, 0.0, 0.0, 1.0),
                ..default()
            })),
            // Skinning ignores this transform; the ray-traced copy is placed by it.
            if settings.mode == "bind-copy-offset" {
                Transform::from_xyz(1.0, 0.0, 0.0)
            } else {
                Transform::default()
            },
            NoFrustumCulling,
        ))
        .id();
    if settings.mode == "morph" {
        commands
            .entity(entity)
            .insert(MeshMorphWeights::Value { weights: vec![1.0] });
    }
    if matches!(
        settings.mode.as_str(),
        "native" | "bind-copy" | "bind-copy-offset"
    ) {
        let joint0 = commands.spawn(Transform::IDENTITY).id();
        let joint1 = commands.spawn(Transform::from_rotation(rotation)).id();
        // Independent original fixture: identity bind poses, upper vertices fully on joint 1.
        let inverse = poses.add(vec![Mat4::IDENTITY; 2]);
        commands.entity(entity).insert(SkinnedMesh {
            inverse_bindposes: inverse,
            joints: vec![joint0, joint1],
        });
    }
    if settings.ray {
        commands.entity(entity).insert(RaytracingMesh3d(ray_mesh));
    }
    println!(
        "Procedural two-joint prism; mode={}; angle={}; no downloaded assets",
        settings.mode, settings.angle
    );
}
