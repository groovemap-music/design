# Spike gm-design-chw.1 — PostgreSQL 19 + pgvector 0.8.6 source build.
#
# Base: official, unmodified postgres:19beta3-alpine, pinned by digest.
# PG19 GA was not yet released when this spike ran (2026-09-23); this was the
# newest PG19 tag published to Docker Hub at that time (no beta4 tag existed).
FROM postgres@sha256:b8e68149dff78f8c379e7d8d6b3dd3c3cff74c9d4dad83118ed11b9d4e9ba3e9

# pgvector 0.8.6, built from source against this image's own LLVM/clang 21
# toolchain (matches upstream postgres:19-alpine's bundled LLVM major version).
# Build tools are installed and removed within the same layer to avoid
# growing the image (~1 MB net increase measured in the planner's local run).
RUN apk add --no-cache --virtual .build-deps git build-base clang21 llvm21 \
    && git clone --depth 1 --branch v0.8.6 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && make -C /tmp/pgvector OPTFLAGS="" \
    && make -C /tmp/pgvector install \
    && rm -rf /tmp/pgvector \
    && apk del .build-deps
