MAME clone for testing a compact + Stock Car set (rdtrack.stockcar).

Paste the INPUT_PORTS block after racedrivc's, the ROM_START block after
racedrivc's, the GAME line after racedrivc's GAME line, add `racedrivcs`
under `racedrivc` in src/mame/mame.lst, then (from the rdp-sidepod README):

    make SUBTARGET=hd SOURCES=src/mame/atari/harddriv.cpp TOOLS=0 -j8
    ./hd racedrivcs -rompath /path/holding/a/racedrivcs/folder

The clone declares the 256 KB DSK halves and the six object EPROMs; every
other file is racedrivc's (their checksums will be reported wrong, which is
only a warning).

The input block is racedrivc's with the cockpit's names for the unused 8-bit
channels.  (An earlier version put a "Brake Pedal" on 12-bit channel 1; that
was wrong - the in-game sampler at 0x04DD0C only selects 12-bit channels, it
never reads them.  The compact's brake is the 8-bit channel 6 "Force Brake",
and the reason the car only crept in MAME was NVRAM: the brake RANGE word at
zram 0xFF4400 is 0 in MAME's stock compact NVRAM, which the brake routine
0x024D80 reads as full brake.  rd.lua writes the block once; NOTES.md
"Compact brake calibration".)

Selection dials are integrators: rd.lua AUTOSEL=1 coins up, picks slot 1 and
the automatic car, and holds the shifter in Drive (N toggles neutral).

static INPUT_PORTS_START( racedrivcs )
	PORT_START("mainpcb:IN0")       /* 60c000 */
	PORT_DIPNAME( 0x01, 0x01, "Diagnostic jumper" )
	PORT_DIPSETTING(    0x01, DEF_STR( Off ) )
	PORT_DIPSETTING(    0x00, DEF_STR( On ) )
	PORT_BIT( 0x02, IP_ACTIVE_LOW, IPT_CUSTOM )    /* HBLANK */
	PORT_BIT( 0x04, IP_ACTIVE_LOW, IPT_CUSTOM ) PORT_READ_LINE_DEVICE_MEMBER("mainpcb:screen", FUNC(screen_device::vblank))
	PORT_BIT( 0x08, IP_ACTIVE_HIGH, IPT_CUSTOM )   /* 12-bit EOC */
	PORT_BIT( 0x10, IP_ACTIVE_HIGH, IPT_CUSTOM ) PORT_READ_LINE_DEVICE_MEMBER("mainpcb:adc8", FUNC(adc0808_device::eoc_r))
	PORT_SERVICE( 0x20, IP_ACTIVE_LOW )
	PORT_BIT( 0x40, IP_ACTIVE_LOW, IPT_COIN2 )
	PORT_BIT( 0x80, IP_ACTIVE_LOW, IPT_COIN1 )

	PORT_START("mainpcb:SW1")       /* 60c002 */
	PORT_DIPNAME( 0x01, 0x01, "SW1:8" )
	PORT_DIPSETTING(    0x01, DEF_STR( Off ) )
	PORT_DIPSETTING(    0x00, DEF_STR( On ) )
	PORT_DIPNAME( 0x02, 0x02, "SW1:7" )
	PORT_DIPSETTING(    0x02, DEF_STR( Off ) )
	PORT_DIPSETTING(    0x00, DEF_STR( On ) )
	PORT_DIPNAME( 0x04, 0x04, "SW1:6" )
	PORT_DIPSETTING(    0x04, DEF_STR( Off ) )
	PORT_DIPSETTING(    0x00, DEF_STR( On ) )
	PORT_DIPNAME( 0x08, 0x08, "SW1:5" )
	PORT_DIPSETTING(    0x08, DEF_STR( Off ) )
	PORT_DIPSETTING(    0x00, DEF_STR( On ) )
	PORT_DIPNAME( 0x10, 0x10, "SW1:4" )
	PORT_DIPSETTING(    0x10, DEF_STR( Off ) )
	PORT_DIPSETTING(    0x00, DEF_STR( On ) )
	PORT_DIPNAME( 0x20, 0x20, "SW1:3" )
	PORT_DIPSETTING(    0x20, DEF_STR( Off ) )
	PORT_DIPSETTING(    0x00, DEF_STR( On ) )
	PORT_DIPNAME( 0x40, 0x40, "SW1:2" )
	PORT_DIPSETTING(    0x40, DEF_STR( Off ) )
	PORT_DIPSETTING(    0x00, DEF_STR( On ) )
	PORT_DIPNAME( 0x80, 0x80, "SW1:1" )
	PORT_DIPSETTING(    0x80, DEF_STR( Off ) )
	PORT_DIPSETTING(    0x00, DEF_STR( On ) )

	PORT_START("mainpcb:a80000")
	PORT_BIT( 0x0001, IP_ACTIVE_LOW, IPT_START2 ) PORT_NAME("Abort")
	PORT_BIT( 0x0002, IP_ACTIVE_LOW, IPT_START1 ) PORT_NAME("Key")
	PORT_BIT( 0x0004, IP_ACTIVE_LOW, IPT_COIN3 )    /* aux coin */
	PORT_BIT( 0x00f8, IP_ACTIVE_LOW, IPT_UNUSED )
	PORT_BIT( 0x0100, IP_ACTIVE_LOW, IPT_BUTTON2 )  PORT_NAME("1st Gear")
	PORT_BIT( 0x0200, IP_ACTIVE_LOW, IPT_BUTTON3 )  PORT_NAME("2nd Gear")
	PORT_BIT( 0x0400, IP_ACTIVE_LOW, IPT_BUTTON4 )  PORT_NAME("3rd Gear")
	PORT_BIT( 0x0800, IP_ACTIVE_LOW, IPT_BUTTON5 )  PORT_NAME("4th Gear")
	PORT_BIT( 0x3000, IP_ACTIVE_LOW, IPT_UNUSED )
	PORT_BIT( 0x4000, IP_ACTIVE_LOW, IPT_CUSTOM )  /* center edge on steering wheel */
	PORT_BIT( 0x8000, IP_ACTIVE_LOW, IPT_UNUSED )

	PORT_START("mainpcb:8BADC.0")        /* b00000 - 8 bit ADC 0 - gas pedal */
	PORT_BIT( 0xff, 0x00, IPT_PEDAL ) PORT_SENSITIVITY(25) PORT_KEYDELTA(20) PORT_NAME("Gas Pedal")

	PORT_START("mainpcb:8BADC.1")        /* b00000 - 8 bit ADC 1 - clutch pedal */
	PORT_BIT( 0xff, 0x00, IPT_PEDAL3 ) PORT_SENSITIVITY(25) PORT_KEYDELTA(100) PORT_NAME("Clutch Pedal")

	PORT_START("mainpcb:8BADC.2")        /* b00000 - 8 bit ADC 2 */
	PORT_BIT( 0xff, IP_ACTIVE_LOW, IPT_UNUSED )

	PORT_START("mainpcb:8BADC.3")        /* b00000 - 8 bit ADC 3 */
	PORT_BIT( 0xff, IP_ACTIVE_LOW, IPT_UNUSED )

	PORT_START("mainpcb:8BADC.4")        /* b00000 - 8 bit ADC 4 */
	PORT_BIT( 0xff, IP_ACTIVE_LOW, IPT_UNUSED )

	PORT_START("mainpcb:8BADC.5")        /* b00000 - 8 bit ADC 5 */
	PORT_BIT( 0xff, IP_ACTIVE_LOW, IPT_UNUSED )

	PORT_START("mainpcb:8BADC.6")        /* b00000 - 8 bit ADC 6 - force brake */
	PORT_BIT( 0xff, 0x20, IPT_PEDAL2 ) PORT_MINMAX(0x20, 0xf0) PORT_SENSITIVITY(25) PORT_KEYDELTA(40) PORT_REVERSE PORT_NAME("Force Brake")

	PORT_START("mainpcb:8BADC.7")        /* b00000 - 8 bit ADC 7 */
	PORT_BIT( 0xff, IP_ACTIVE_LOW, IPT_UNUSED )

	PORT_START("mainpcb:12BADC.0")       /* 400000 - steering wheel */
	PORT_BIT( 0xfff, 0x800, IPT_PADDLE ) PORT_MINMAX(0x010, 0xff0) PORT_SENSITIVITY(400) PORT_KEYDELTA(5) PORT_NAME("Steering Wheel")

	/* dummy ADC ports to end up with the same number as the full version */
	PORT_START("mainpcb:12BADC.1")
	PORT_BIT( 0xfff, IP_ACTIVE_LOW, IPT_UNUSED )

	PORT_START("mainpcb:12BADC.2")
	PORT_BIT( 0xfff, IP_ACTIVE_LOW, IPT_UNUSED )
	PORT_START("mainpcb:12BADC.3")
	PORT_BIT( 0xfff, IP_ACTIVE_LOW, IPT_UNUSED )
INPUT_PORTS_END

ROM_START( racedrivcs )   // compact + the Panorama's Stock Car track (rdtrack.stockcar): 256 KB DSK, six object EPROMs
	ROM_REGION( 0x100000, "mainpcb:maincpu", 0 )        /* 1MB for 68000 code */
	ROM_LOAD16_BYTE( "136078-5002.200r", 0x000000, 0x010000, CRC(ae8f79bd) SHA1(054f2d1948d6d03832c4557c3dd7667c0784716d) )
	ROM_LOAD16_BYTE( "136078-5001.210r", 0x000001, 0x010000, CRC(ad896e7f) SHA1(7b047f0c972fac075db00faf19cdf9ccdcef5c63) )
	ROM_LOAD16_BYTE( "136078-5004.200s", 0x020000, 0x010000, CRC(b8650bee) SHA1(a9905081e622e4a4fcec9aa08b87566ecdb9198b) )
	ROM_LOAD16_BYTE( "136078-5003.210s", 0x020001, 0x010000, CRC(bf56a29f) SHA1(1ef17dab9ed1fd92b005dd31f7dccf1535583ec4) )
	ROM_LOAD16_BYTE( "136078-5006.200t", 0x040000, 0x010000, CRC(8559a61b) SHA1(ad1796c39ac9cbb50e8a97d9e8c9cd5adfd0ff5e) )
	ROM_LOAD16_BYTE( "136078-5005.210t", 0x040001, 0x010000, CRC(33d654b1) SHA1(1e6886d49008b13886184c9ced0f6bd642d9562c) )
	ROM_LOAD16_BYTE( "136078-4008.200u", 0x060000, 0x010000, CRC(5b119d16) SHA1(ec808b5e325ab1a6dbddcef75871cd0126a98377) )
	ROM_LOAD16_BYTE( "136078-4007.210u", 0x060001, 0x010000, CRC(fa234861) SHA1(4c6753c64f942f6ea98f96e1e8f4de880800573e) )
	ROM_LOAD16_BYTE( "136078-4010.200v", 0x080000, 0x010000, CRC(150acc9e) SHA1(e172e6a1ed5ac0791fe053d4bde2d0c62202f399) )
	ROM_LOAD16_BYTE( "136078-4009.210v", 0x080001, 0x010000, CRC(85a9aa37) SHA1(e403a41c44edfca190cb15452d67a427de9cf56e) )
	ROM_LOAD16_BYTE( "136077-1012.200w", 0x0a0000, 0x010000, CRC(9a78b952) SHA1(53270d4d8c28579ebda477a63c034f6d1b9e5a58) )
	ROM_LOAD16_BYTE( "136077-1011.210w", 0x0a0001, 0x010000, CRC(c5cd5491) SHA1(ede5a3bb888342032d6758b0fb149451b6543d8b) )
	ROM_LOAD16_BYTE( "136077-1014.200x", 0x0c0000, 0x010000, CRC(a872792a) SHA1(9269e397567940013e5f46cadfe2bad2ca1a2bc4) )
	ROM_LOAD16_BYTE( "136077-1013.210x", 0x0c0001, 0x010000, CRC(ca7b3e53) SHA1(cdb3a6360893fd3dd2947c050dca8a4dfaa9ced9) )
	ROM_LOAD16_BYTE( "136078-4016.200y", 0x0e0000, 0x010000, CRC(aa296776) SHA1(991e33568e47a82cb183724f7df1f835850c30fa) )
	ROM_LOAD16_BYTE( "136078-4015.210y", 0x0e0001, 0x010000, CRC(030c803d) SHA1(bb249c9d1d28f6851a529b93c4f96d80665f2bce) )

	ROM_REGION( 0x2000, "mainpcb:asic65:asic65cpu", 0 )   /* ASIC65 TMS32015 code */
	ROM_LOAD( "136077-1027.30j", 0x00000, 0x02000, NO_DUMP )

	ROM_REGION( 0x20000, "mainpcb:harddriv_sound:soundcpu", 0 )        /* 2*64k for audio 68000 code */
	ROM_LOAD16_BYTE( "136077-1032.70n", 0x000000, 0x008000, CRC(fbc903a6) SHA1(047240a5192918ced52d90b0555ba2e19a26329e) )
	ROM_LOAD16_BYTE( "136077-1033.45n", 0x000001, 0x008000, CRC(e032ca7c) SHA1(a80c980c8e58cf8cada72140e42a3cd1ea987b3d) )

	ROM_REGION16_BE( 0x60000, "mainpcb:user1", 0 )  /* 384k for ADSP object ROM */
	ROM_LOAD16_BYTE( "136077-1021.10h", 0x000000, 0x010000, CRC(9831fe73) SHA1(5215ee89a0014399b7d829e443b16590a4679844) )
	ROM_LOAD16_BYTE( "136077-1023.10k", 0x000001, 0x010000, CRC(74bf0e0e) SHA1(a3d91ecf13c3619e073324517a4a5afaae831982) )
	ROM_LOAD16_BYTE( "136077-1022.10j", 0x020000, 0x010000, CRC(c0393c31) SHA1(31726c01eb0d4650936908c90d45161197b7efba) )
	ROM_LOAD16_BYTE( "136077-1024.10l", 0x020001, 0x010000, CRC(1e2fb25f) SHA1(4940091bbad6144bce091d2737191d266d4b0310) )
	ROM_LOAD16_BYTE( "136088-1022.9h", 0x040000, 0x010000, NO_DUMP )
	ROM_LOAD16_BYTE( "136088-1021.9k", 0x040001, 0x010000, NO_DUMP )

	ROM_REGION16_BE( 0x50000, "mainpcb:user3", 0 )  /* 256k for DSK ROMs + 64k for RAM */
	ROM_LOAD16_BYTE( "136078-1030.30e", 0x000000, 0x020000, NO_DUMP )
	ROM_LOAD16_BYTE( "136078-1031.10e", 0x000001, 0x020000, NO_DUMP )

	ROM_REGION( 0x50000, "mainpcb:harddriv_sound:serialroms", 0 )      /* 10*128k for audio serial ROMs */
	ROM_LOAD( "136052-1123.65a", 0x000000, 0x010000, CRC(a88411dc) SHA1(1fd53c7eadffa163d5423df2f8338757e58d5f2e) )
	ROM_LOAD( "136052-1124.55a", 0x010000, 0x010000, CRC(071a4309) SHA1(c623bd51d6a4a56503fbf138138854d6a30b11d6) )
	ROM_LOAD( "136052-3125.45a", 0x020000, 0x010000, CRC(856548ff) SHA1(e8a17b274185c5e4ecf5f9f1c211e18b3ef2456d) )
	ROM_LOAD( "136052-1126.30a", 0x030000, 0x010000, CRC(f46ef09c) SHA1(ba62f73ee3b33d8f26b430ffa468f8792dca23de) )
	ROM_LOAD( "136077-1017.45c", 0x040000, 0x010000, CRC(e93129a3) SHA1(1221b08c8efbfd8cf6bfbfd956545f10bef48663) )

	ROM_REGION( 0x800, "mainpcb:200e", 0 )
	ROM_LOAD( "racedrivc.200e",  0x000000, 0x000800, CRC(2c0f7715) SHA1(79cf3a6cd48fc4a86cd94e823243fc0cd4bffa57) )

	ROM_REGION( 0x800, "mainpcb:210e", 0 )
	ROM_LOAD( "racedrivc.210e",  0x000000, 0x000800, CRC(2e843742) SHA1(bc73ab0270cdf45aaa1a19703e8c3aa916578ef0) )
ROM_END

GAME(  1990, racedrivcs,  racedriv, racedrivc_machine,  racedrivcs, harddriv_new_state, empty_init, ROT0, "Atari Games", "Race Drivin' (compact, Stock Car track)", 0 )
