#!/usr/bin/env bash

echo PWD: `pwd`
export

cp -v /opt/postgres/pg_hba.conf /var/lib/postgresql/data/pg_hba.conf
