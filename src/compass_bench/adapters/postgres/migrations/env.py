"""Alembic environment: migrate over the connection that connection.upgrade_to_head opens."""

from alembic import context

from compass_bench.adapters.postgres.schema import metadata


def run_migrations() -> None:
    context.configure(connection=context.config.attributes["connection"], target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()
    return


# Alembic executes this module's top level when it loads it, so the module is never __main__
run_migrations()
