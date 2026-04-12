FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY . /build-context

RUN python -m pip install --no-cache-dir "PyYAML>=6" "numpy>=1.26" "onnxruntime>=1.17.0" "speexdsp-ns>=0.1.2" "wyoming>=1.6.0" \
    && if [ -d /build-context/rootfs/app ]; then \
         src=/build-context/rootfs/app; \
         run=/build-context/run.sh; \
        elif [ -d /build-context/addon/homewakeword/rootfs/app ]; then \
         src=/build-context/addon/homewakeword/rootfs/app; \
         run=/build-context/addon/homewakeword/run.sh; \
       else \
         echo "missing add-on app bundle in build context" >&2; \
         exit 1; \
       fi \
    && cp -R "$src"/. /app/ \
    && cp "$run" /usr/local/bin/run.sh \
    && chmod +x /usr/local/bin/run.sh \
    && rm -rf /build-context

EXPOSE 10700

ENTRYPOINT ["/usr/local/bin/run.sh"]
