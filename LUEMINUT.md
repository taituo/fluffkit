# furby-fi: Furby Connect puhuu suomea

Työkalu muuttaa suomenkielisen tekstin Furbyn omaksi ääneksi. Se tekee TTS:n, koodaa äänen A18-muotoon ja rakentaa siitä DLC-paketin. Paketti ladataan Furbyyn BLE:n yli, ja fraasit soitetaan PyFluffin action-komennolla. Ääni kuuluu Furbyn omasta kaiuttimesta ja liikkeet ja silmät tulevat mukaan, joten erillistä kaiutinta ei tarvita.

## Mitä on tarkistettu (ilman oikeaa Furbya)

- **Avoimessa A1800-enkooderissa oli bugi, ja korjasin sen** (`a1800/furby-fi-encoder-fix.diff`, `a1800/NOTICE`). John-K:n enkooderi skaalasi kvantisoinnin väärällä skaalausparametrilla. Testasin saman lähdeäänen kolmella tavalla, ja vertailukohtana on Furbhaxin alkuperäinen A1800.DLL:llä koodattu tiedosto:

  | | korrelaatio | SNR | äänenvoimakkuus |
  |---|---|---|---|
  | Alkuperäinen A1800.DLL (Windows) | 0.961 | 11.1 dB | 0.97 |
  | John-K enkooderi sellaisenaan | 0.865 | 6.0 dB | 1.37 (liian kova) |
  | **Korjattu enkooderi** | **0.961** | **11.1 dB** | **0.97** |

  Korjatun enkooderin gainit ja kehysparametrit ovat identtiset DLL:n kanssa noin 95 %:ssa kehyksistä. Ajoitus täsmää DLL:ään (ensimmäinen kehys pudotetaan), ja otsake on samassa muodossa kuin Furbyn omissa raidoissa (pituus = kehystavut + 2, 16000). Suomenkielisellä testifraasilla koko putken tulos on korrelaatio 0.987 ja SNR 16 dB. Codecin omat 52 testiä menevät läpi.
- **Dekooderi toimii oikeilla Furby-tiedostoilla:** kaikki 146 raitaa Hasbron DLC:stä purkautuvat.
- **DLC rakentuu oikein.** Muutoksia tulee vain AMF- (ääni) ja APL-osioihin (soittolistat), muut 7 osiota ovat tavu tavulta samat kuin alkuperäisessä. Otsakkeen offsetit täsmäävät tiedoston kokoon, ja jokainen fraasi osoittaa omaan raitaansa.
- **Ei testattu oikealla Furbyllä.** Itse latausmenetelmä on kuitenkin sama, jolla Context IS (2017) ja furpy3 (2026) ovat soittaneet omaa ääntä oikeassa Furbyssä: pohjana `tu003410.dlc`, raidat minifioidaan 128 tavuun ja ääni vaihdetaan input-75-toimintoihin.

## Asennus: Steam Deck (Desktop mode, Konsole)

```bash
# 1) ffmpeg ilman pacmania (SteamOS:n juuri on read-only)
mkdir -p ~/.local/bin && cd /tmp
curl -LO https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
tar xf ffmpeg-release-amd64-static.tar.xz && cp ffmpeg-*-static/ffmpeg ~/.local/bin/

# 2) tämä paketti + PyFluff (BLE)
cd ~ && git clone https://github.com/<sinä>/furby-fi && (cd furby-fi/a1800 && cargo build --release)   # Rust: rustup kotihakemistoon
git clone https://github.com/martinwoodward/PyFluff
python3 -m venv ~/furbyenv && ~/furbyenv/bin/pip install -e ~/PyFluff
alias furby='~/furbyenv/bin/python ~/furby-fi/furbyfi.py'
```

Valmiiksi käännetty `a1800_codec` löytyy myös Releases-sivulta (Linux x86-64 / macOS arm64): laita se kansioon `bin/`. MacBookilla: `brew install ffmpeg rust`.

## Käyttö

```bash
export OPENAI_API_KEY=sk-...
furby slots                                   # 60 fraasipaikkaa
furby pack fraasit.txt -o furby_fi.dlc --pitch 3
furby check furby_fi.dlc --export kuuntele/   # pura WAViksi ja kuuntele ennen latausta
furby upload furby_fi.dlc                     # noin 1,5–2 min
furby say 1                                   # tai: furby say "kutittaa"
```

- `fraasit.txt` sisältää yhden fraasin per rivi. Rivi voi olla teksti (TTS) tai polku `.wav`-, `.mp3`- tai `.a18`-tiedostoon, eli voit käyttää myös omaa nauhoitettua ääntäsi.
- `--pitch 3` nostaa ääntä 3 puolisäveltä tempoa muuttamatta, ja tulos kuulostaa Furbymaisemmalta.
- TTS:n valitset valitsimella `--engine openai` (oletus, `gpt-4o-mini-tts`, malli vaihtuu muuttujalla `FURBY_TTS_MODEL`), `--engine piper --voice fi_FI-harri-medium.onnx` tai `--engine espeak`. Saman tekstin TTS-tulos tallennetaan välimuistiin, joten pakettia voi muokata ja rakentaa uudelleen ilman uusia API-kutsuja.
- Ilman API-avainta: `--engine espeak` (robottiääni, mutta riittää latauksen testaamiseen).

## Jos fraasi ei soi

1. Avaa Furbyn debug-näyttö (`~/furbyenv/bin/pyfluff debug`, toista kunnes näkyy slot-sivu). Slotin numero kertoo tilan: `0` tyhjä, `1` lataus kesken tai epäonnistui, `2` ladattu, `3` aktiivinen.
2. Käynnistä Furby uudelleen. furpy3:n mukaan Furby tarvitsee uudelleenkäynnistyksen kahden päivityksen välillä.
3. Kokeile toista slotia: `--slot 1`. Slotteja on 2M, 1M ja 0.5M, ja paketin koko on noin 300 kB + ääni.
4. Pahin tapaus: FurBLE-reset (ylösalaisin, kieli pohjassa, häntää vedetään noin 10 s) tyhjentää DLC-muistin.

## Rajat

- Paketissa voi olla enintään 60 fraasia. 16 kbps vie noin 2 kB sekunnissa, ja BLE siirtää noin 4 kB sekunnissa.
- Uusi fraasi vaatii koko paketin uudelleenlatauksen (noin 1,5 min), joten LLM-vastaukset eivät tule Furbyn omalla äänellä reaaliajassa. Reaaliaikaiseen keskusteluun kannattaa käyttää ulkoista kaiutinta. Furbyn oma ääni sopii valmiisiin fraaseihin, kuten kotiautomaation ilmoituksiin, iltarutiineihin ja reaktioihin.
- Suun liike (LPS) käyttää alkuperäisen raidan kuviota. Lipsync omasta äänestä on seuraava askel, mutta LPS-formaatin ajoitusyksikkö on vielä purkamatta.

## Lähteet

- Korjattu enkooderi: John-K/a1800_codec (Apache-2.0)
- DLC-formaatti: Context IS / ctxis Furby, mmaker/furpy3 (`dlcpack.py` on oma, MIT-lisensoitu toteutus, tuottaa tavu tavulta saman tuloksen)
- BLE: PyFluff, bluefluff
- Vertailudata: swarley7/furbhax
