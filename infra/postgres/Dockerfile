# The PostgreSQL server of ASLMS with pgvector (design research-index, decision 14): the same postgres:16.15 server
# build as before, plus PGDG's pgvector package pinned exactly from the PGDG repository the image already carries.
# Nothing else is installed. The data volume and the server major version are unchanged, so the cluster starts on the
# same volume. `vector` is not a trusted extension: migration 0042 creates it through `migrate` as the cluster
# superuser. CI installs the same pinned package into its postgres:16.15 service container (a guard test compares the
# two pins). When PGDG withdraws the pinned build the image build fails: move the pin in one commit, here and in CI.
# The build is `+1`, not `+2`: `0.8.7-1.pgdg13+2` depends on `postgresql-16 (>> 16.16)` and would replace the server with
# 16.16; the last line refuses any pin that changes the server package (design research-index, Deviations 14).
FROM postgres:16.15

ARG PGVECTOR_VERSION=0.8.7-1.pgdg13+1

RUN apt-get update \
    && apt-get install -y --no-install-recommends "postgresql-16-pgvector=${PGVECTOR_VERSION}" \
    && rm -rf /var/lib/apt/lists/* \
    && test -f /usr/share/postgresql/16/extension/vector.control \
    && test "$(dpkg-query -W -f='${Version}' postgresql-16)" = "${PG_VERSION}"
