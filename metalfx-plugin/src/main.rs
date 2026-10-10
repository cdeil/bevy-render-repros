use bevy::{
    camera::{Hdr, RenderTarget},
    core_pipeline::tonemapping::{DebandDither, Tonemapping},
    prelude::*,
    render::{
        pipelined_rendering::PipelinedRenderingPlugin,
        render_resource::{TextureFormat, TextureUsages},
        view::window::screenshot::{Screenshot, save_to_disk},
    },
    window::ExitCondition,
};
use bevy_metalfx::{
    MetalFxEffectState, MetalFxEffectStatus, MetalFxMode, MetalFxObservationFrame, MetalFxPlugin,
};

#[derive(Resource)]
struct Target(Handle<Image>);

fn main() {
    let args: Vec<_> = std::env::args().collect();
    let mode = match args.get(1).map(String::as_str) {
        Some("disabled") => MetalFxMode::Disabled,
        Some("spatial") => MetalFxMode::Spatial,
        Some("temporal") => MetalFxMode::Temporal,
        _ => panic!("metalfx-plugin-repro <disabled|spatial|temporal> <new.png>"),
    };
    let output = args.get(2).expect("output path").clone();
    assert!(
        !std::path::Path::new(&output).exists(),
        "Use a new output path"
    );
    let expected_unavailable = args.iter().any(|a| a == "--expect-unavailable");
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
    .add_plugins(MetalFxPlugin {
        mode,
        render_scale: 0.5,
        ..default()
    })
    .add_systems(Startup, setup);
    app.finish();
    app.cleanup();
    let mut completed_updates = 0;
    let mut requested = false;
    for update in 0..1200 {
        app.update();
        let frame = app.world().resource::<MetalFxObservationFrame>().0;
        let snapshots = app
            .world()
            .resource::<MetalFxEffectStatus>()
            .snapshots(frame);
        let ready = (expected_unavailable
            && snapshots
                .iter()
                .any(|s| s.state() == MetalFxEffectState::Unavailable))
            || mode == MetalFxMode::Disabled
            || snapshots
                .iter()
                .any(|s| s.state() == MetalFxEffectState::OutputWritten);
        if ready {
            completed_updates += 1;
        } else {
            completed_updates = 0;
        }
        if update > 100 && completed_updates >= 8 && !requested {
            println!("Current-frame effect evidence: {snapshots:?}");
            let image = app.world().resource::<Target>().0.clone();
            app.world_mut()
                .spawn(Screenshot::image(image))
                .observe(save_to_disk(output.clone()));
            requested = true;
        }
        if requested && std::path::Path::new(&output).is_file() {
            println!(
                "Completed screenshot readback; mode={mode:?}; update={update}; ready={ready}"
            );
            return;
        }
        std::thread::sleep(std::time::Duration::from_millis(5));
    }
    panic!("No completed output for {mode:?}; refusing a pending/fallback screenshot");
}
fn setup(
    mut commands: Commands,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<StandardMaterial>>,
    mut images: ResMut<Assets<Image>>,
) {
    let mut image = Image::new_target_texture(512, 512, TextureFormat::Rgba8UnormSrgb, None);
    image.texture_descriptor.usage |= TextureUsages::COPY_SRC;
    let image = images.add(image);
    commands.insert_resource(Target(image.clone()));
    commands.spawn((
        Camera3d::default(),
        RenderTarget::Image(image.into()),
        Transform::from_xyz(0.0, 0.0, 4.0).looking_at(Vec3::ZERO, Vec3::Y),
        Hdr,
        Msaa::Off,
        Tonemapping::None,
        DebandDither::Disabled,
    ));
    for i in 0..11 {
        commands.spawn((
            Mesh3d(meshes.add(Cuboid::new(0.025, 1.5, 0.025))),
            MeshMaterial3d(materials.add(StandardMaterial {
                unlit: true,
                base_color: Color::srgb_u8(180, 100, 40),
                ..default()
            })),
            Transform::from_xyz((i as f32 - 5.0) * 0.12, 0.0, 0.0)
                .with_rotation(Quat::from_rotation_z(0.35)),
        ));
    }
}
