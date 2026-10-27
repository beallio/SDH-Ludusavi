use super::*;
use client::LudusaviPaths;

pub(super) fn migrate(
    paths: &LudusaviPaths,
    mut config_show: impl FnMut(&Path) -> Result<Value, String>,
) -> io::Result<()> {
    let native = &paths.native_config;
    let flatpak = &paths.flatpak_config;
    if let (Ok(native), Ok(flatpak)) = (native.canonicalize(), flatpak.canonicalize())
        && native == flatpak
    {
        return Ok(());
    }

    let native_config = native.join("config.yaml");
    let flatpak_config = flatpak.join("config.yaml");
    if missing(&native_config)? && regular_file(&flatpak_config)? {
        prepare_copy(&flatpak_config, native)?
            .persist_noclobber(&native_config)
            .map_err(|error| error.error)?;
    }

    let manifest = native.join("manifest.yaml");
    let cache = native.join("cache.yaml");
    let source_manifest = flatpak.join("manifest.yaml");
    let source_cache = flatpak.join("cache.yaml");
    if !missing(&manifest)?
        || !missing(&cache)?
        || !regular_file(&source_manifest)?
        || !regular_file(&source_cache)?
    {
        return Ok(());
    }

    let source_url = manifest_url(&flatpak_config, native, &mut config_show)?;
    let target_url = manifest_url(&native_config, native, &mut config_show)?;
    if source_url.is_none() || source_url != target_url || !missing(&manifest)? || !missing(&cache)?
    {
        return Ok(());
    }

    let manifest_copy = prepare_copy(&source_manifest, native)?;
    let cache_copy = prepare_copy(&source_cache, native)?;
    if !missing(&manifest)? || !missing(&cache)? {
        return Ok(());
    }
    manifest_copy
        .persist_noclobber(manifest)
        .map_err(|error| error.error)?;
    cache_copy
        .persist_noclobber(cache)
        .map_err(|error| error.error)?;
    Ok(())
}

/// `config show` writes default `config.yaml` and `cache.yaml` files into the folder it reads,
/// so read the address from a private copy instead of either real folder.
fn manifest_url(
    config: &Path,
    scratch_parent: &Path,
    config_show: &mut impl FnMut(&Path) -> Result<Value, String>,
) -> io::Result<Option<String>> {
    fs::create_dir_all(scratch_parent)?;
    let scratch = tempfile::Builder::new()
        .prefix(".sdh-ludusavi-")
        .tempdir_in(scratch_parent)?;
    if regular_file(config)? {
        fs::copy(config, scratch.path().join("config.yaml"))?;
    }
    let output = config_show(scratch.path()).map_err(io::Error::other)?;
    Ok(output
        .pointer("/manifest/url")
        .and_then(Value::as_str)
        .map(str::to_owned))
}

fn missing(path: &Path) -> io::Result<bool> {
    match fs::symlink_metadata(path) {
        Ok(_) => Ok(false),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(true),
        Err(error) => Err(error),
    }
}

fn regular_file(path: &Path) -> io::Result<bool> {
    match fs::metadata(path) {
        Ok(metadata) => Ok(metadata.is_file()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error),
    }
}

fn prepare_copy(source: &Path, directory: &Path) -> io::Result<tempfile::NamedTempFile> {
    fs::create_dir_all(directory)?;
    let mut temporary = tempfile::Builder::new()
        .prefix(".sdh-ludusavi-")
        .tempfile_in(directory)?;
    io::copy(&mut fs::File::open(source)?, temporary.as_file_mut())?;
    temporary.as_file().sync_all()?;
    Ok(temporary)
}
