use std::{future::Future, sync::LazyLock};

use tokio::runtime::{Builder, Runtime};

static RUNTIME: LazyLock<Result<Runtime, String>> = LazyLock::new(|| {
    Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
        .map_err(|error| error.to_string())
});

pub(crate) fn block_on<T>(future: impl Future<Output = T>) -> Result<T, String> {
    let runtime = RUNTIME.as_ref().map_err(Clone::clone)?;
    Ok(runtime.block_on(future))
}
