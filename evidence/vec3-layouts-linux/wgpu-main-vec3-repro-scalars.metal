// language: metal1.0
#include <metal_stdlib>
#include <simd/simd.h>

using metal::uint;

struct Counts {
    uint x;
    uint y;
    uint z;
};

kernel void main_(
  device Counts& counts [[user(fake0)]]
) {
    counts = Counts {1u, 2u, 3u};
    return;
}
