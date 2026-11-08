; Lanceur .prg : 10 SYS 2061, affiche le titre, joue la musique sous interruption.
        .segment "CODE"
        .word basic_fin
        .word 10
        .byte $9E, "2061", 0
basic_fin:
        .word 0
        lda #$93            ; efface l'écran
        jsr $FFD2
        ldx #0
@titre: lda titre,x
        beq @fin
        jsr $FFD2
        inx
        bne @titre
@fin:   sei
        lda #$36            ; BASIC coupé : les données peuvent dépasser $A000
        sta $01
        jsr $1000
        lda #<irq
        sta $0314
        lda #>irq
        sta $0315
        lda #$F9            ; minuterie du CIA 1 à 50 Hz (PAL : 985 248 / 50)
        sta $DC04
        lda #$4C
        sta $DC05
        lda #$11
        sta $DC0E
        cli
@attente:
        jmp @attente
irq:    jsr $1003
        jmp $EA31
titre:  ; le titre (PETSCII, terminé par 0) est ajouté ici par atelier_sid
