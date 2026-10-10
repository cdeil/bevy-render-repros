use bevy::{
    asset::embedded_asset,
    camera::RenderTarget,
    core_pipeline::tonemapping::{DebandDither, Tonemapping},
    prelude::*,
    render::{
        pipelined_rendering::PipelinedRenderingPlugin,
        render_resource::{AsBindGroup, TextureFormat, TextureUsages},
        view::window::screenshot::{Screenshot, save_to_disk},
    },
    shader::ShaderRef,
    window::ExitCondition,
};

#[derive(Asset, TypePath, AsBindGroup, Debug, Clone)]
struct MarkerMaterial {}
impl Material for MarkerMaterial {
    fn fragment_shader() -> ShaderRef {
        "embedded://bevy_capture_repro/marker.wesl".into()
    }
}
#[derive(Resource)]
struct Target(Handle<Image>);

fn main() {
    let args: Vec<_> = std::env::args().collect();
    let output = args
        .iter()
        .position(|s| s == "--out")
        .and_then(|i| args.get(i + 1))
        .expect("--out <path.png>")
        .clone();
    let late = args.iter().any(|s| s == "--late");
    let adjacent = args.iter().any(|s| s == "--adjacent-late");
    let asynchronous = args.iter().any(|s| s == "--async");
    let mut app = App::new();
    app.add_plugins(
        DefaultPlugins
            .set(bevy::render::RenderPlugin {
                synchronous_pipeline_compilation: !asynchronous,
                ..default()
            })
            .set(WindowPlugin {
                primary_window: None,
                exit_condition: ExitCondition::DontExit,
                ..default()
            })
            .disable::<PipelinedRenderingPlugin>(),
    );
    if !late && !adjacent {
        embedded_asset!(app, "marker.wesl");
    }
    app.add_plugins(MaterialPlugin::<MarkerMaterial>::default())
        .add_systems(Startup, setup);
    if adjacent {
        embedded_asset!(app, "marker.wesl");
    }
    app.finish();
    app.cleanup();
    // Late registration deliberately allows the consumer's asset request to fail first.
    // Ordinary adjacent plugin registration may race; this isolates the ordering contract.
    for frame in 0..160 {
        if late && frame == 30 {
            embedded_asset!(app, "marker.wesl");
        }
        app.update();
        if frame == 0 || frame == 5 || frame == 100 {
            let target = app.world().resource::<Target>().0.clone();
            let path = output.replace(".png", &format!("-{frame}.png"));
            app.world_mut()
                .spawn(Screenshot::image(target))
                .observe(save_to_disk(path));
        }
        std::thread::sleep(std::time::Duration::from_millis(5));
    }
    println!("Completed 160 updates; late={late}; asynchronous={asynchronous}");
}
fn setup(
    mut commands: Commands,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<MarkerMaterial>>,
    mut images: ResMut<Assets<Image>>,
) {
    let mut image = Image::new_target_texture(256, 256, TextureFormat::Rgba8UnormSrgb, None);
    image.texture_descriptor.usage |= TextureUsages::COPY_SRC;
    let target = images.add(image);
    commands.insert_resource(Target(target.clone()));
    commands.spawn((
        Camera3d::default(),
        RenderTarget::Image(target.into()),
        Transform::from_xyz(0.0, 0.0, 3.0).looking_at(Vec3::ZERO, Vec3::Y),
        Msaa::Off,
        Tonemapping::None,
        DebandDither::Disabled,
    ));
    commands.spawn((
        Mesh3d(meshes.add(Cuboid::new(1.0, 1.0, 1.0))),
        MeshMaterial3d(materials.add(MarkerMaterial {})),
        Transform::default(),
    ));
}
