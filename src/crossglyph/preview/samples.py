"""The text the preview opens on, one preset per language.

A specimen you cannot read tells you nothing about a font you are choosing, so
the page picks a preset from the browser's own languages on a first visit. Each
one is built the same way:

* the pangram the firmware itself shows under Settings > Font, taken from
  `lib/I18n/translations/<language>.yaml`, `STR_FONT_PREVIEW_TEXT`. It is the
  string the device puts under a font name, so the preview and the device agree
  on what a font's preview text is;
* Article 1 of the Universal Declaration of Human Rights in that language. It
  is a published translation rather than something invented here, it exists for
  every language on this list, and it runs long enough to wrap four or five
  times, which is what shows line breaking, justification and hyphenation;
* a short English paragraph, so a reader whose font has to carry both scripts
  can see them beside each other, and so every preset shows digits.

Some presets add a paragraph of their own digits: English and Russian because
the `figures` knob is what it shows, and Arabic because the tail's digits are
Latin and say nothing about whether a face carries the Arabic-Indic ten.

Emphasis sits inside running text rather than on a line of its own, because
that is where you can tell whether an italic is the right weight beside its own
roman. A face the font does not carry falls back to regular, as it does on the
device.

Japanese and Chinese carry no marks. The layout engine takes a style per word
and this markup follows it, so a mark anywhere inside a word styles all of it
(see markup.parse) -- and a paragraph with no spaces in it is one word. The
English paragraph carries the emphasis for those two.
"""
from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class Sample:
    """One preset: what the picker calls it, and what goes in the box."""

    #: The language's own name for itself, which is what somebody looking for
    #: their own language scans the list for.
    name: str
    text: str


#: Closes every preset but English, whose own text is already English. The fox
#: is the English pangram; the figures sentence is here rather than in each
#: language because a row of 1s shows what the `figures` knob does without
#: needing prose around it, and 1 is the digit tabular figures pad most.
_ENGLISH_TAIL = (
    "The quick brown fox jumps over the lazy dog. _Typography_ is what "
    "language looks like, and at this size every *hinting* decision shows. "
    "Tabular figures share one width, so a 1 keeps the gaps around it: "
    "111 118 181 811 1118.")


def _preset(pangram: str, article: str) -> str:
    return "\n".join([pangram, article, _ENGLISH_TAIL])


#: Keyed by the tag the page matches `navigator.languages` against, in the
#: order the picker lists them, which is alphabetical by English name rather
#: than by the endonym shown -- sorting 日本語 against Suomi has no answer.
SAMPLES: dict[str, Sample] = {
    "ar": Sample("العربية", "\n".join([
        # The pangram every Arabic type specimen shows: all twenty-eight
        # letters, and enough of them joining to show a face's initial, medial
        # and final forms in one line.
        "نص حكيم له سر قاطع وذو شأن عظيم مكتوب على ثوب أخضر ومغلف بجلد أزرق",
        # Second, as in English and Russian, so the digits land on the first
        # page rather than past its end. Arabic-Indic digits rather than the
        # English tail's Latin ones: they are a separate ten glyphs in a
        # separate block, and a face can carry the Latin set and none of these.
        "الأرقام: ٠ ١ ٢ ٣ ٤ ٥ ٦ ٧ ٨ ٩، كما في الصفحة ١١٨ من طبعة سنة ١٩٤٧.",
        # Bold and no italic: Arabic is not set in italic, and the faces that
        # ship one for it are rare. The English tail carries the italic.
        "يولد جميع الناس أحرارًا متساوين في الكرامة والحقوق. وقد وهبوا عقلاً "
        "وضميرًا وعليهم أن يعامل بعضهم بعضًا *بروح الإخاء*.",
        _ENGLISH_TAIL])),

    "zh-Hans": Sample("简体中文", _preset(
        # No pangram exists for a script of this size. The Thousand Character
        # Classic is the closest thing the tradition has: a thousand
        # characters, no two the same, and known to anyone who went to school.
        "天地玄黄，宇宙洪荒。日月盈昃，辰宿列张。",
        "人人生而自由，在尊严和权利上一律平等。"
        "他们赋有理性和良心，并应以兄弟关系的精神相对待。")),

    "zh-Hant": Sample("繁體中文", _preset(
        "天地玄黃，宇宙洪荒。日月盈昃，辰宿列張。",
        "人人生而自由，在尊嚴和權利上一律平等。"
        "他們賦有理性和良心，並應以兄弟關係的精神相對待。")),

    "en": Sample("English", "\n".join([
        "The quick brown fox jumps over the lazy dog.",
        # Second, so the digits land on the first page rather than past its
        # end. Heavy on 1s on purpose: it is the digit tabular figures pad
        # most, so the `figures` knob shows here or nowhere.
        "Figures in text: 11 January 1918, page 118, 1,710 miles and 15 per "
        "cent. Tabular figures share one width, so a 1 keeps the gaps around "
        "it: 111 118 181 811 1118.",
        "All human beings are born free and equal in dignity and rights. They "
        "are endowed with _reason and conscience_ and should act towards one "
        "another in a *spirit of brotherhood*.",
        "_Typography_ is what language looks like, and at this size every "
        "*hinting* decision shows, from the shape of a comma to where the "
        "line breaks."])),

    "fi": Sample("Suomi", _preset(
        "Törkylempijävongahdus",
        "Kaikki ihmiset syntyvät vapaina ja tasavertaisina arvoltaan ja "
        "oikeuksiltaan. Heille on annettu _järki ja omatunto_, ja heidän on "
        "toimittava toisiaan kohtaan *veljeyden hengessä*.")),

    "fr": Sample("Français", _preset(
        "Portez ce vieux whisky au juge blond qui fume",
        "Tous les êtres humains naissent libres et égaux en dignité et en "
        "droits. Ils sont doués de _raison et de conscience_ et doivent agir "
        "les uns envers les autres dans un *esprit de fraternité*.")),

    "de": Sample("Deutsch", _preset(
        "Victor jagt zwölf Boxkämpfer quer über den großen Sylter Deich",
        "Alle Menschen sind frei und gleich an Würde und Rechten geboren. Sie "
        "sind mit _Vernunft und Gewissen_ begabt und sollen einander im "
        "*Geist der Brüderlichkeit* begegnen.")),

    "it": Sample("Italiano", _preset(
        "Pranzo d'acqua fa volti sghembi",
        "Tutti gli esseri umani nascono liberi ed eguali in dignità e "
        "diritti. Essi sono dotati di _ragione e di coscienza_ e devono agire "
        "gli uni verso gli altri in *spirito di fratellanza*.")),

    "ja": Sample("日本語", _preset(
        # The Iroha, which is a pangram: every kana of the classical syllabary
        # exactly once. It is what a Japanese type specimen has shown for a
        # thousand years.
        "いろはにほへと ちりぬるを わかよたれそ つねならむ "
        "うゐのおくやま けふこえて あさきゆめみし ゑひもせす",
        "すべての人間は、生まれながらにして自由であり、かつ、"
        "尊厳と権利とについて平等である。人間は、理性と良心とを授けられており、"
        "互いに同胞の精神をもって行動しなければならない。")),

    "ko": Sample("한국어", _preset(
        "다람쥐 헌 쳇바퀴에 타고파",
        "모든 인간은 태어날 때부터 자유로우며 그 존엄과 권리에 있어 "
        "동등하다. 인간은 천부적으로 _이성과 양심을_ 부여받았으며 서로 "
        "*형제애의 정신으로* 행동하여야 한다.")),

    "pl": Sample("Polski", _preset(
        "Pchnąć w tę łódź jeża lub ośm skrzyń fig",
        "Wszyscy ludzie rodzą się wolni i równi pod względem swej godności i "
        "swych praw. Są oni obdarzeni _rozumem i sumieniem_ i powinni "
        "postępować wobec innych w *duchu braterstwa*.")),

    "ru": Sample("Русский", "\n".join([
        "Съешь ещё этих мягких французских булок, да выпей же чаю.",
        "Цифры в прозе: 11 января 1918 года, 101-й полк, 1710 рублей 15 "
        "копеек, страница 118 — у табличных цифр ширина общая, и вокруг "
        "единицы остаются заметные просветы: 111 118 181 811 1118.",
        "Широкая электрификация южных губерний даст _мощный толчок_ подъёму "
        "сельского хозяйства, и по всему выходит, что дело это *долгое*, "
        "хлопотное и *_совершенно необходимое_*.",
        "Строка должна где-то переноситься, и именно здесь становится видно, "
        "как расставлены пробелы при выключке по формату и где переносчик "
        "решил разорвать длинное слово.",
        "The quick brown fox jumps over the lazy dog. _Typography_ is what "
        "language looks like, and at this size every hinting decision shows."])),

    "es": Sample("Español", _preset(
        "Benjamín pidió una bebida de kiwi y fresa. Noé, sin vergüenza, la "
        "más exquisita champaña del menú.",
        "Todos los seres humanos nacen libres e iguales en dignidad y "
        "derechos y, dotados como están de _razón y conciencia_, deben "
        "comportarse *fraternalmente* los unos con los otros.")),

    "sv": Sample("Svenska", _preset(
        "Flygande bäckasiner söka hwila på mjuka tuvor",
        "Alla människor äro födda fria och lika i värde och rättigheter. De "
        "äro utrustade med _förnuft och samvete_ och böra handla gentemot "
        "varandra i *en anda av broderskap*.")),

    "uk": Sample("Українська", _preset(
        "Єхидна, ґава, їжак ще й шиплячі плазуни бігцем форсують Янцзи",
        "Всі люди народжуються вільними і рівними у своїй гідності та правах. "
        "Вони наділені _розумом і совістю_ і повинні діяти у відношенні один "
        "до одного в *дусі братерства*.")),
}

#: What a request with no text of its own is drawn with. English rather than
#: the language this was written in: it is the one preset a reader of any of
#: the others is most likely to have a second language in.
SAMPLE_TEXT = SAMPLES["en"].text
