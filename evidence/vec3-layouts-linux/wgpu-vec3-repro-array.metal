// language: metal1.0
#include <metal_stdlib>
#include <simd/simd.h>

using metal::uint;

struct type_1 {
    uint inner[3];
};

kernel void main_(
  device type_1& counts [[user(fake0)]]
) {
    counts = type_1 {{1u, 2u, 3u}};
    return;
}
