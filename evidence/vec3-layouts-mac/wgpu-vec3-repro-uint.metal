// language: metal1.0
#include <metal_stdlib>
#include <simd/simd.h>

using metal::uint;


kernel void main_(
  device metal::uint3& counts [[user(fake0)]]
) {
    counts = metal::uint3(1u, 2u, 3u);
    return;
}
