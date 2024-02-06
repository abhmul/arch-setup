# arch-setup
Setup for my computers running arch.

## Resources and Credit
Additional wallpapers can be found on my [Google Drive](https://drive.google.com/file/d/1TNlT0TVXBd0uAJsXYJWkcc6zVywIOynb/view?usp=sharing). Credit goes to [Yteci](https://www.reddit.com/r/masseffect/comments/2alwa1/i_made_these_minimalisticish_wallpapers_and/). Unfortunately I cannot make this link public as I do not have permission from the author to reupload to a public link. These original link for the hi-res versions of these wallpapers is now dead, so I may be the one of the only people who still has a copy of the hi-res versions. Please email me at abhmul@gmail.com if you would like to access these.

## Checklist
- [x] ~~Add installation of google drive `setup.sh`~~ Replaced with rclone
- [x] Setup google drive folder and test
- [x] Download/fix webcam drivers - no fix needed
- [x] Test getting onto a zoom call
- [ ] ~~Setup Rofi desktop app manager~~ just using i3-dmenu-desktop for now 
  - see https://www.youtube.com/watch?v=TutfIwxSE_s
  - https://github.com/davatorium/rofi
- [x] Add to i3blocks
  - [x] Mute on or off?
  - [x] Mic on or off?
  - [x] Webcam on or off?
  - [x] Filesystem free space
  - [ ] ~~CPU load with ema~~
- [ ] Add installation of miniconda to `setup.sh`
- [ ] Fix brightness control
- [ ] Change home and root file system space to be SPACE_USED/TOTAL_SPACE

- [ ] Add installation of below to `setup.sh`
  - [ ] yay
  - [ ] i3, i3blocks
  - [ ] network-manager
  - [ ] blueman
- [ ] Add setup of i3blocks to `setup.sh`
- [ ] Fix dktest errors
- [ ] Test using the GPU through docker
- [ ] Copy over various commands and files made from the [Install i3 on Arch](https://gist.github.com/fjpalacios/441f2f6d27f25ee238b9bfcb068865db) tutorial.
- [ ] Add .xinitrc to this repository and symlink it onto computer
- [ ] add no-notifications extension to i3 config and test it out
- [ ] add auto-start of some applications on startup
  - [ ] browser - ws 2
  - [ ] terminals - ws 1
  - [ ] obsidian - ws 3
- [ ] Investigate use of Optimus to save battery
- [ ] Change terminal theme