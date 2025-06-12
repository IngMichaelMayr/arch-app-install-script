# Arch Linux App Installation Script
A Python Installation Script that helps installing arch and flatpak based applications. You can define groups of applications in a JSON File that shall be installed. With this script you can setup several Laptops with the same applications in short time.

## Files needed
Define a JSON File named packages.json and insert the applications you want to be installed via pacman or flatpak.

NOTE: 
A "global" group is required. It can stay empty, but must be defined!
If you want to use flatpak for installation, please ensure that it is contained in the JSON File at the top in one of the installation groups.

## Useage 
Start installation process with `python install-packages.py`
Enter password if needed and enjoy the show!

