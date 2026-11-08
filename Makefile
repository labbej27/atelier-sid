# Assemble le lecteur 6502 et le lanceur .prg avec cc65. Les binaires sont
# versionnés dans atelier_sid/bin : le logiciel n'a pas besoin de cc65.
all: atelier_sid/bin/player.bin atelier_sid/bin/stub.bin

atelier_sid/bin/player.bin: lecteur/player.s lecteur/frequences.inc lecteur/player.cfg
	cd lecteur && cl65 -g -t none -C player.cfg -o ../$@ -Ln ../atelier_sid/bin/player.lbl player.s && rm -f player.o

atelier_sid/bin/stub.bin: lecteur/stub.s lecteur/stub.cfg
	cd lecteur && cl65 -t none -C stub.cfg -o ../$@ stub.s && rm -f stub.o
