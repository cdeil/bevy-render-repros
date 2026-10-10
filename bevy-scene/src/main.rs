use bevy::{
    camera::{CameraMainTextureUsages, RenderTarget},
    mesh::Indices,
    prelude::*,
    render::{
        pipelined_rendering::PipelinedRenderingPlugin,
        render_resource::{TextureFormat, TextureUsages},
        view::window::screenshot::{Screenshot, save_to_disk},
    },
    solari::prelude::{RaytracingMesh3d, SolariLighting, SolariPlugins},
    window::ExitCondition,
};

#[derive(Resource)]
struct Settings {
    solari: bool,
    output: String,
}

#[derive(Resource)]
struct Target(Handle<Image>);

fn main() {
    let args: Vec<_> = std::env::args().collect();
    let solari = !args.iter().any(|s| s == "--raster");
    let output = args
        .iter()
        .position(|s| s == "--out")
        .and_then(|i| args.get(i + 1))
        .expect("pass --out <absolute screenshot.png>")
        .clone();
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
    .insert_resource(Settings {
        solari,
        output: output.clone(),
    })
    .add_systems(Startup, setup);
    if solari {
        app.add_plugins(SolariPlugins);
    }
    app.finish();
    app.cleanup();
    for frame in 0..160 {
        app.update();
        if frame == 100 {
            let target = app.world().resource::<Target>().0.clone();
            app.world_mut()
                .spawn(Screenshot::image(target))
                .observe(save_to_disk(output.clone()));
        }
        std::thread::sleep(std::time::Duration::from_millis(5));
    }
    assert!(
        std::path::Path::new(&output).is_file(),
        "Screenshot missing; run did not demonstrate a completed frame"
    );
    println!("160 updates completed; screenshot saved; solari={solari}");
}

fn setup(
    mut commands: Commands,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<StandardMaterial>>,
    mut images: ResMut<Assets<Image>>,
    settings: Res<Settings>,
) {
    let mut image = Image::new_target_texture(512, 512, TextureFormat::Rgba8UnormSrgb, None);
    image.texture_descriptor.usage |= TextureUsages::COPY_SRC;
    let target = images.add(image);
    commands.insert_resource(Target(target.clone()));
    let mut camera = commands.spawn((
        Camera3d::default(),
        RenderTarget::Image(target.into()),
        Transform::from_xyz(3.0, 2.5, 5.0).looking_at(Vec3::new(0.0, 0.5, 0.0), Vec3::Y),
        Msaa::Off,
    ));
    if settings.solari {
        camera.insert((
            SolariLighting::default(),
            CameraMainTextureUsages::default().with(TextureUsages::STORAGE_BINDING),
        ));
    }
    for (shape, position, colour) in [
        (
            Cuboid::new(1.0, 1.0, 1.0),
            Vec3::new(0.0, 0.6, 0.0),
            Color::srgb(0.3, 0.6, 0.8),
        ),
        (
            Cuboid::new(8.0, 0.1, 8.0),
            Vec3::ZERO,
            Color::srgb(0.5, 0.5, 0.5),
        ),
    ] {
        let mut mesh = Mesh::from(shape);
        mesh.generate_tangents().unwrap();
        if let Some(Indices::U16(indices)) = mesh.indices() {
            mesh.insert_indices(Indices::U32(
                indices.iter().map(|&i| u32::from(i)).collect(),
            ));
        }
        let mesh = meshes.add(mesh);
        let mut entity = commands.spawn((
            Mesh3d(mesh.clone()),
            MeshMaterial3d(materials.add(StandardMaterial {
                base_color: colour,
                ..default()
            })),
            Transform::from_translation(position),
        ));
        if settings.solari {
            entity.insert(RaytracingMesh3d(mesh));
        }
    }
    commands.spawn((
        DirectionalLight {
            illuminance: 15000.0,
            ..default()
        },
        Transform::from_xyz(2.0, 4.0, 2.0).looking_at(Vec3::ZERO, Vec3::Y),
    ));
    println!(
        "Procedural cube and floor; no downloaded assets; output={}",
        settings.output
    );
}
