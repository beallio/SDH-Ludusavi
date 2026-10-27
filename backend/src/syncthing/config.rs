use super::*;
#[derive(Clone, Debug)]
struct SyncthingConfig {
    api_key: String,
    api_url: Option<String>,
}

fn api_url_from_gui_address(address: Option<&str>, tls: bool) -> Option<String> {
    let address = address?.trim();
    if address.is_empty() {
        return None;
    }
    if address.contains("://") {
        return Some(address.trim_end_matches('/').to_owned());
    }
    let address = if address.starts_with(':') {
        format!("127.0.0.1{address}")
    } else if let Some(port) = address.strip_prefix("0.0.0.0:") {
        format!("127.0.0.1:{port}")
    } else if address == "0.0.0.0" {
        "127.0.0.1:8384".to_owned()
    } else if let Some(port) = address.strip_prefix("[::]:") {
        format!("[::1]:{port}")
    } else if address == "[::]" {
        "[::1]:8384".to_owned()
    } else {
        address.to_owned()
    };
    Some(format!(
        "{}://{address}",
        if tls { "https" } else { "http" }
    ))
}

fn parse_syncthing_config(path: &Path) -> Option<SyncthingConfig> {
    let text = fs::read_to_string(path).ok()?;
    parse_xml_config(&text).or_else(|| parse_regex_config(&text))
}

fn parse_xml_config(text: &str) -> Option<SyncthingConfig> {
    let mut reader = Reader::from_str(text);
    let mut in_gui = false;
    let mut tls = false;
    let mut field = None;
    let mut key = String::new();
    let mut address = String::new();
    loop {
        match reader.read_event() {
            Ok(Event::Start(element)) => {
                let name = element.local_name();
                if name.as_ref() == b"gui" && !in_gui {
                    in_gui = true;
                    for attr in element.attributes().with_checks(false) {
                        let attr = attr.ok()?;
                        if attr.key.local_name().as_ref() == b"tls" {
                            let value = attr.decode_and_unescape_value(reader.decoder()).ok()?;
                            tls = xml_true(&value);
                        }
                    }
                } else if in_gui {
                    field = match name.as_ref() {
                        b"apikey" => Some(0),
                        b"address" => Some(1),
                        _ => None,
                    };
                }
            }
            Ok(Event::Text(value)) if in_gui => {
                let decoded = value.decode().ok()?;
                let decoded = quick_xml::escape::unescape(&decoded).ok()?;
                match field {
                    Some(0) => key.push_str(&decoded),
                    Some(1) => address.push_str(&decoded),
                    _ => (),
                }
            }
            Ok(Event::CData(value)) if in_gui => {
                let decoded = value.decode().ok()?;
                match field {
                    Some(0) => key.push_str(&decoded),
                    Some(1) => address.push_str(&decoded),
                    _ => (),
                }
            }
            Ok(Event::GeneralRef(value)) if in_gui => {
                let target = match field {
                    Some(0) => &mut key,
                    Some(1) => &mut address,
                    _ => continue,
                };
                if let Some(character) = value.resolve_char_ref().ok()? {
                    target.push(character);
                } else {
                    target.push_str(quick_xml::escape::resolve_xml_entity(
                        &value.decode().ok()?,
                    )?);
                }
            }
            Ok(Event::End(element)) if in_gui => match element.local_name().as_ref() {
                b"apikey" | b"address" => field = None,
                b"gui" => break,
                _ => (),
            },
            Ok(Event::Eof) => break,
            Err(_) => return None,
            _ => (),
        }
    }
    let api_key = key.trim();
    if api_key.is_empty() {
        return None;
    }
    Some(SyncthingConfig {
        api_key: api_key.to_owned(),
        api_url: api_url_from_gui_address(
            (!address.trim().is_empty()).then_some(address.trim()),
            tls,
        ),
    })
}

fn parse_regex_config(text: &str) -> Option<SyncthingConfig> {
    let start = tag_start(text, "gui")?;
    let open_end = text[start..].find('>')? + start;
    let close = text[open_end + 1..].find("</gui>")? + open_end + 1;
    let attributes = &text[start + 4..open_end];
    let body = &text[open_end + 1..close];
    let tls = attributes
        .split_whitespace()
        .find_map(|part| {
            let (name, value) = part.split_once('=')?;
            if name != "tls" {
                return None;
            }
            Some(xml_true(value.trim_matches(['\'', '"'])))
        })
        .unwrap_or(false);
    let api_key = extract_tag(body, "apikey")?;
    let api_key = api_key.trim();
    if api_key.is_empty() {
        return None;
    }
    let address = extract_tag(body, "address");
    Some(SyncthingConfig {
        api_key: api_key.to_owned(),
        api_url: api_url_from_gui_address(address.as_deref(), tls),
    })
}

fn tag_start(text: &str, tag: &str) -> Option<usize> {
    let needle = format!("<{tag}");
    let mut offset = 0;
    while let Some(index) = text[offset..].find(&needle) {
        let start = offset + index;
        let boundary = text.as_bytes().get(start + needle.len()).copied()?;
        if boundary.is_ascii_whitespace() || boundary == b'>' {
            return Some(start);
        }
        offset = start + needle.len();
    }
    None
}

fn extract_tag(text: &str, tag: &str) -> Option<String> {
    let start = tag_start(text, tag)?;
    let open_end = text[start..].find('>')? + start;
    let close = text[open_end + 1..].find(&format!("</{tag}>"))? + open_end + 1;
    Some(text[open_end + 1..close].to_owned())
}

fn xml_true(value: &str) -> bool {
    matches!(
        value
            .trim()
            .trim_matches(['\'', '"'])
            .to_ascii_lowercase()
            .as_str(),
        "true" | "1" | "yes" | "on"
    )
}

pub(super) fn expand_path(path: &str) -> PathBuf {
    if let Some(rest) = path.strip_prefix("~/") {
        return env::var_os("HOME").map_or_else(
            || PathBuf::from(path),
            |home| PathBuf::from(home).join(rest),
        );
    }
    if path == "~" {
        return env::var_os("HOME").map_or_else(|| PathBuf::from(path), PathBuf::from);
    }
    PathBuf::from(path)
}

fn candidate_config_files() -> Vec<PathBuf> {
    let home = env::var_os("HOME").map(PathBuf::from).unwrap_or_default();
    let mut candidates = Vec::new();
    for (name, append) in [
        ("SYNCTHING_CONFIG_FILE", None),
        ("STCONFDIR", Some("config.xml")),
        ("STHOMEDIR", Some("config.xml")),
    ] {
        if let Some(value) = env::var_os(name).filter(|value| !value.is_empty()) {
            let path = expand_path(&value.to_string_lossy());
            candidates.push(if let Some(file) = append {
                path.join(file)
            } else {
                path
            });
        }
    }
    for (variable, default, suffix) in [
        ("XDG_STATE_HOME", ".local/state", "syncthing/config.xml"),
        ("XDG_CONFIG_HOME", ".config", "syncthing/config.xml"),
        ("XDG_DATA_HOME", ".local/share", "syncthing/config.xml"),
    ] {
        if let Some(value) = env::var_os(variable).filter(|value| !value.is_empty()) {
            candidates.push(expand_path(&value.to_string_lossy()).join(suffix));
        }
        candidates.push(home.join(default).join(suffix));
    }
    let current_flatpak_id = env::var("FLATPAK_ID").unwrap_or_default();
    for id in std::iter::once(current_flatpak_id.trim())
        .filter(|id| !id.is_empty())
        .chain(COMMON_FLATPAK_IDS)
    {
        let base = home.join(".var/app").join(id);
        for subpath in [
            "config/syncthing/config.xml",
            "data/syncthing/config.xml",
            ".config/syncthing/config.xml",
            ".local/state/syncthing/config.xml",
            ".local/share/syncthing/config.xml",
        ] {
            candidates.push(base.join(subpath));
        }
    }
    let mut seen = HashSet::new();
    candidates.retain(|path| seen.insert(path.clone()));
    candidates
}

pub(super) fn resolve_api_credentials() -> Result<(String, String), String> {
    let config = candidate_config_files()
        .iter()
        .find_map(|path| parse_syncthing_config(path));
    let key = env::var("SYNCTHING_API_KEY")
        .ok()
        .filter(|key| !key.is_empty())
        .or_else(|| config.as_ref().map(|config| config.api_key.clone()));
    if key.is_none() {
        let configured = env::var_os("SYNCTHING_API_URL").is_some()
            || candidate_config_files().iter().any(|path| path.is_file());
        return Err(if configured {
            "No Syncthing API key found."
        } else {
            "No Syncthing configuration found."
        }
        .to_owned());
    }
    let url = env::var("SYNCTHING_API_URL")
        .ok()
        .filter(|url| !url.is_empty())
        .or_else(|| config.and_then(|config| config.api_url))
        .unwrap_or_else(|| DEFAULT_API_URL.to_owned());
    Ok((
        url.trim_end_matches('/').to_owned(),
        key.unwrap().trim().to_owned(),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::syncthing::api::is_loopback_url;
    #[test]
    fn gui_addresses_and_loopback_validation() {
        for (address, tls, expected) in [
            (Some("127.0.0.1:8384"), false, Some("http://127.0.0.1:8384")),
            (Some("127.0.0.1:8384"), true, Some("https://127.0.0.1:8384")),
            (Some("0.0.0.0:8384"), false, Some("http://127.0.0.1:8384")),
            (Some(":8384"), false, Some("http://127.0.0.1:8384")),
            (Some("[::]:8384"), false, Some("http://[::1]:8384")),
            (Some(""), false, None),
        ] {
            assert_eq!(api_url_from_gui_address(address, tls).as_deref(), expected);
        }
        for host in [
            "http://127.1.2.3:8384",
            "https://[::1]:8384",
            "http://localhost:8384",
        ] {
            assert!(
                Url::parse(host).is_ok_and(|url| is_loopback_url(&url)),
                "{host}"
            );
        }
        for host in [
            "http://192.168.1.50:8384",
            "http://steamdeck.local:8384",
            "http://0.0.0.0:8384",
            "ftp://127.0.0.1:8384",
        ] {
            assert!(
                !Url::parse(host).is_ok_and(|url| is_loopback_url(&url)),
                "{host}"
            );
        }
    }

    #[test]
    fn xml_credentials_decode_character_and_predefined_references() {
        let input = r#"<configuration><gui><address>127.0.0.1:83&#56;&#x34;/a&amp;b</address><apikey> A&#99;&#x63;&amp;&lt;&gt;&apos;&quot; Z </apikey></gui></configuration>"#;
        let parsed = parse_xml_config(input).unwrap();
        assert_eq!(parsed.api_key, "Acc&<>'\" Z");
        assert_eq!(parsed.api_url.as_deref(), Some("http://127.0.0.1:8384/a&b"));
    }

    #[test]
    fn xml_and_regex_fallback_parse_tls_and_credentials() {
        for input in [
            r#"<configuration><gui tls="true"><address>127.0.0.1:8384</address><apikey>testkey</apikey></gui></configuration>"#,
            r#"<configuration><gui tls='true'><address>127.0.0.1:8384</address><apikey>testkey</apikey></gui></configuration>"#,
        ] {
            let parsed = parse_xml_config(input)
                .or_else(|| parse_regex_config(input))
                .unwrap();
            assert_eq!(parsed.api_key, "testkey");
            assert_eq!(parsed.api_url.as_deref(), Some("https://127.0.0.1:8384"));
        }
        assert!(
            parse_xml_config("invalid")
                .or_else(|| parse_regex_config("invalid"))
                .is_none()
        );
        let malformed = r#"<configuration><gui tls="true"><address>127.0.0.1:8384</address><apikey>testkey</apikey></gui>"#;
        assert_eq!(
            parse_regex_config(malformed).unwrap().api_url.as_deref(),
            Some("https://127.0.0.1:8384")
        );
    }
}
