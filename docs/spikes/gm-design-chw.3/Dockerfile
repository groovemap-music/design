FROM postgres@sha256:b8e68149dff78f8c379e7d8d6b3dd3c3cff74c9d4dad83118ed11b9d4e9ba3e9
RUN apk add --no-cache --virtual .build-deps git build-base clang21 llvm21 \
    && git clone --depth 1 --branch v0.8.6 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && make -C /tmp/pgvector OPTFLAGS="" \
    && make -C /tmp/pgvector install \
    && rm -rf /tmp/pgvector \
    && apk del .build-deps
