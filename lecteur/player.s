; Lecteur SID d'Atelier SID : 3 voix, appelé 50 fois par seconde (PAL).
; Chargé en $1000. Les flux des voix suivent le lecteur en mémoire ; leurs
; adresses, les instruments et le filtre sont écrits par atelier_sid/export.py
; dans l'en-tête ci-dessous.
;
; Format d'un flux (une commande, ses paramètres, puis une durée en trames) :
;   $00-$5F d      note (0 = C0), avec attaque
;   $60 d          silence (relâche)
;   $61 k n.. d    arpège de k notes, une par trame
;   $65 n d        note liée, sans nouvelle attaque
;   $66 i          change d'instrument (pas de durée)
;   $70-$73 d      batterie : grosse caisse, caisse claire, charleston, tom
;   $FF            fin : retour au début du flux
;
; Instrument (8 octets) :
;   0 forme d'onde (registre de contrôle, sans le bit de gâchette)
;   1 attaque/déclin   2 maintien/relâche
;   3-4 largeur d'impulsion de départ (12 bits)
;   5 vitesse de variation de la largeur d'impulsion (0 = fixe)
;   6 vibrato : profondeur (bits 4-7, 0 à 4) et trames par pas (bits 0-3)
;   7 drapeaux : bit 0 filtre, bit 2 relâche d'une trame avant chaque attaque

SID     = $D400
PTR     = $FB           ; pointeur de lecture en page zéro, sauvé et restauré

        .segment "CODE"
        jmp init
        jmp play
flux:       .word 0, 0, 0       ; $1006 adresses des trois flux
instr_voix: .byte 0, 1, 2       ; $100C instrument de départ de chaque voix
filtre:     .byte 0, $40, $00, $1F  ; $100F coupure basse, haute, résonance (bits 4-7), mode|volume
instruments:                    ; $1013 huit instruments de 8 octets
        .res 64, 0

; ---------------------------------------------------------------------------
init:   ldx #$18
        lda #0
@efface:
        sta SID,x
        dex
        bpl @efface
        ldx #2
@voix:  txa
        asl
        tay
        lda flux,y
        sta ptrlo,x
        lda flux+1,y
        sta ptrhi,x
        lda #1
        sta minuterie,x
        lda #0
        sta mode,x
        sta gachette,x
        lda instr_voix,x
        jsr charger_instr
        dex
        bpl @voix
        lda filtre
        sta SID+$15
        lda filtre+1
        sta SID+$16
        lda filtre+3
        sta SID+$18
        jmp routage

; --- Charge l'instrument A dans la voix X ---
charger_instr:
        asl
        asl
        asl
        tay
        lda instruments,y
        sta onde,x
        lda instruments+3,y
        sta pwlo,x
        lda instruments+4,y
        sta pwhi,x
        lda instruments+5,y
        sta pwv,x
        lda instruments+6,y
        sta vib,x
        lda instruments+7,y
        sta drapeaux,x
        lda instruments+1,y
        pha
        lda instruments+2,y
        ldy decal,x
        sta SID+6,y
        pla
        sta SID+5,y
        lda #0
        sta pwdir,x
        sta vibcpt,x
        sta vibpas,x
        ; la voix entre ou sort du filtre
routage:
        stx sauvex
        lda filtre+2
        and #$F0
        ldx #2
@r:     ldy drapeaux,x
        sty tmp
        lsr tmp
        bcc :+
        ora bitvoix,x
:       dex
        bpl @r
        sta SID+$17
        ldx sauvex
        rts

; ---------------------------------------------------------------------------
play:   lda PTR
        pha
        lda PTR+1
        pha
        ldx #0
@boucle:
        jsr voix
        inx
        cpx #3
        bne @boucle
        pla
        sta PTR+1
        pla
        sta PTR
        rts

voix:   ldy decal,x
        sty reg
        lda gachette,x          ; attaque différée d'une trame après la relâche
        beq :+
        lda #0
        sta gachette,x
        lda onde,x
        ora #1
        sta SID+4,y
:       dec minuterie,x
        bne effets
        jsr suivant
effets: lda mode,x
        cmp #1
        bne :+
        jsr pwm
        jmp vibrato
:       cmp #2
        bne :+
        jsr pwm
        jmp arpege
:       cmp #3
        bne :+
        jmp batterie
:       rts

; --- Largeur d'impulsion qui va et vient entre $100 et $E00 ---
pwm:    lda pwv,x
        beq @fin
        lda pwdir,x
        bne @descend
        lda pwlo,x
        clc
        adc pwv,x
        sta pwlo,x
        bcc :+
        inc pwhi,x
:       lda pwhi,x
        cmp #$0E
        bcc @ecrit
        lda #1
        sta pwdir,x
        bne @ecrit
@descend:
        lda pwlo,x
        sec
        sbc pwv,x
        sta pwlo,x
        bcs :+
        dec pwhi,x
:       lda pwhi,x
        beq :+
        bpl @ecrit
:       lda #1
        sta pwhi,x
        lda #0
        sta pwdir,x
@ecrit: ldy reg
        lda pwlo,x
        sta SID+2,y
        lda pwhi,x
        sta SID+3,y
@fin:   rts

; --- Vibrato : la fréquence oscille autour de la note, en 8 pas ---
vibrato:
        lda vib,x
        and #$F0
        beq @sort
        inc vibcpt,x
        lda vib,x
        and #$0F
        cmp vibcpt,x
        beq :+
        bcs @sort
:       jmp @pas
@sort:  rts
@pas:   lda #0
        sta vibcpt,x
        lda vibpas,x
        clc
        adc #1
        and #7
        sta vibpas,x
        tay
        lda vibforme,y
        sta forme
        and #3
        beq ecrire_base
        ; écart = fréquence >> (9 - profondeur), divisé par 2 aux pas intermédiaires
        lda freqlo,x
        sta dlo
        lda freqhi,x
        sta dhi
        lda vib,x
        lsr
        lsr
        lsr
        lsr
        sta tmp
        lda #9
        sec
        sbc tmp
        tay
        lda forme
        and #1
        beq :+
        iny
:
@decale:
        lsr dhi
        ror dlo
        dey
        bne @decale
        lda forme
        bmi @moins
        lda freqlo,x
        clc
        adc dlo
        sta dlo
        lda freqhi,x
        adc dhi
        jmp @pose
@moins: lda freqlo,x
        sec
        sbc dlo
        sta dlo
        lda freqhi,x
        sbc dhi
@pose:  ldy reg
        sta SID+1,y
        lda dlo
        sta SID,y
@fin:   rts

ecrire_base:
        ldy reg
        lda freqlo,x
        sta SID,y
        lda freqhi,x
        sta SID+1,y
        rts

; --- Arpège : une note de l'accord par trame ---
arpege: ldy arpidx,x
        iny
        tya
        cmp arpnb,x
        bcc :+
        lda #0
:       sta arpidx,x
        txa
        asl
        asl
        clc
        adc arpidx,x
        tay
        lda arpnotes,y
        jsr poser_note
        rts

; --- Lit l'événement suivant du flux de la voix X ---
suivant:
        lda ptrlo,x
        sta PTR
        lda ptrhi,x
        sta PTR+1
        ldy #0
        lda (PTR),y
        cmp #$FF
        bne @pasfin
        txa
        asl
        tay
        lda flux,y
        sta ptrlo,x
        lda flux+1,y
        sta ptrhi,x
        jmp suivant
@pasfin:
        cmp #$60
        bcs @pasnote
        jsr poser_note
        jsr pw_depart
        lda drapeaux,x
        and #4
        beq @directe
        lda onde,x              ; relâche maintenant, attaque à la trame suivante
        ldy reg
        sta SID+4,y
        lda #1
        sta gachette,x
        bne @note
@directe:
        lda onde,x
        and #$FE
        ldy reg
        sta SID+4,y
        ora #1
        sta SID+4,y
@note:  lda #1
        sta mode,x
        ldy #1
        jmp duree
@pasnote:
        cmp #$60
        bne @pasrepos
        lda onde,x
        ldy reg
        sta SID+4,y
        lda #0
        sta mode,x
        ldy #1
        jmp duree
@pasrepos:
        cmp #$61
        bne @pasarp
        iny
        lda (PTR),y
        sta arpnb,x
        sta compte
        txa
        asl
        asl
        sta cible
@copie: iny
        lda (PTR),y
        sty sauvey
        ldy cible
        sta arpnotes,y
        inc cible
        ldy sauvey
        dec compte
        bne @copie
        lda #$FF
        sta arpidx,x
        lda #2
        sta mode,x
        sty sauvey
        jsr pw_depart
        lda onde,x
        ora #1
        ldy reg
        sta SID+4,y
        ldy sauvey
        iny
        jmp duree
@pasarp:
        cmp #$65
        bne @pasliee
        iny
        lda (PTR),y
        jsr poser_note
        lda onde,x
        ora #1
        ldy reg
        sta SID+4,y
        lda #1
        sta mode,x
        ldy #2
        jmp duree
@pasliee:
        cmp #$66
        bne @batt
        iny
        lda (PTR),y
        jsr charger_instr
        lda #2
        jsr avancer
        jmp suivant
@batt:  and #3
        sta typebatt,x
        lda #0
        sta trame,x
        lda #3
        sta mode,x
        ldy #1
duree:  lda (PTR),y             ; Y pointe sur l'octet de durée
        sta minuterie,x
        iny
        tya
avancer:
        clc
        adc ptrlo,x
        sta ptrlo,x
        bcc :+
        inc ptrhi,x
:       rts

; --- Note A : fréquence de base, écrite dans le SID ---
poser_note:
        tay
        lda frqlo,y
        sta freqlo,x
        lda frqhi,y
        sta freqhi,x
        lda #0
        sta vibcpt,x
        sta vibpas,x
        jmp ecrire_base

pw_depart:
        ldy reg
        lda pwlo,x
        sta SID+2,y
        lda pwhi,x
        sta SID+3,y
        rts

; --- Batterie : 5 trames par coup ---
batterie:
        lda trame,x
        cmp #5
        bcc :+
        rts
:       lda typebatt,x
        asl
        asl
        adc typebatt,x          ; type * 5 (retenue nulle : type < 4)
        adc trame,x
        tay
        lda battfrq,y
        sta tmp
        lda battonde,y
        ldy reg
        pha
        lda trame,x
        bne :+
        lda #0                  ; premier pas : gâchette coupée pour relancer l'enveloppe
        sta SID+4,y
:       lda tmp
        sta SID+1,y
        lda #0
        sta SID,y
        pla
        sta SID+4,y
        inc trame,x
        rts

;               grosse caisse         caisse claire         charleston            tom
battfrq:  .byte $18,$0E,$09,$06,$04,  $1C,$30,$28,$20,$18,  $70,$70,$70,$70,$70,  $0C,$0A,$08,$07,$06
battonde: .byte $41,$41,$41,$41,$40,  $41,$81,$81,$81,$80,  $81,$80,$80,$80,$80,  $11,$11,$11,$11,$10

vibforme: .byte $00, $01, $02, $01, $00, $81, $82, $81
decal:    .byte 0, 7, 14
bitvoix:  .byte 1, 2, 4

        .include "frequences.inc"

; Variables : dans l'image elle-même, car les flux sont placés juste après.
ptrlo:      .res 3
ptrhi:      .res 3
minuterie:  .res 3
mode:       .res 3      ; 0 silence, 1 note, 2 arpège, 3 batterie
gachette:   .res 3
onde:       .res 3
pwlo:       .res 3
pwhi:       .res 3
pwv:        .res 3
pwdir:      .res 3
vib:        .res 3
vibcpt:     .res 3
vibpas:     .res 3
drapeaux:   .res 3
freqlo:     .res 3
freqhi:     .res 3
arpnb:      .res 3
arpidx:     .res 3
arpnotes:   .res 12
typebatt:   .res 3
trame:      .res 3
reg:        .res 1
tmp:        .res 1
forme:      .res 1
dlo:        .res 1
dhi:        .res 1
compte:     .res 1
cible:      .res 1
sauvey:     .res 1
sauvex:     .res 1
