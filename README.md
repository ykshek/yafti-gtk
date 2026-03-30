# Bazzite Portal

![Bazzite Portal Screenshot](assets/demo.gif)


A GTK3 interface for the Bazzite Portal, providing quick access to various useful scripts, fixes, and QOL tweaks for the terminal averse.

On installed systems, the default configuration file is located at:
```
/usr/share/yafti/yafti.yml
```

## Installing

On Fedora/Fedora based systems, install the [Terra repository](https://terra.fyralabs.com/).
Then, run the following command:

```
sudo dnf install bazzite-portal
```

## Running

The application requires a YAML configuration file path as a command-line argument.

Action buttons open commands in your system's default terminal through `xdg-terminal-exec`.

### On Bazzite (default config)

```bash
yafti_gtk.py /usr/share/yafti/yafti.yml
```

### With Custom Config

```bash
yafti_gtk.py /path/to/custom/yafti.yml
```

### Desktop Shortcut

The installed desktop file automatically launches with the default Bazzite config path. You can find it in your application menu as "Bazzite Portal".

## Configuration

The app reads a `yafti.yml` configuration file to populate tabs and actions. The YAML file should follow this structure:

```yaml
screens:
  - title: "Category Name"
    actions:
      - title: "Action Title"
        description: "Optional description"
        script: "command to run"
```
