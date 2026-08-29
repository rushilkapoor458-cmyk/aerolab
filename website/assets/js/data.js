/* =============================================================================
   AURELIA — content layer
   Everything the interface renders lives here, so copy, prices and imagery can
   be edited without touching behaviour. Prices are in INR, whole rupees.
   ========================================================================== */

window.AURELIA = (function () {
  'use strict';

  const RESTAURANT = {
    name: 'Aurelia',
    legalName: 'Aurelia Fire Kitchen Pvt. Ltd.',
    tagline: 'Fire, season, memory.',
    phoneDisplay: '+91 22 4000 1890',
    phone: '+912240001890',
    whatsapp: '919820001890',
    email: 'reservations@aurelia.example',
    street: '14 Ashford Lane, Off Carter Road',
    locality: 'Bandra West',
    city: 'Mumbai',
    region: 'MH',
    postal: '400050',
    country: 'IN',
    lat: 19.0596,
    lng: 72.8295,
    priceRange: '₹₹₹₹',
    currency: 'INR',
    deliveryFee: 79,
    freeDeliveryOver: 2500,
    taxRate: 0.05,
    hours: [
      { day: 'Monday',    label: 'Mon', open: null,  close: null },
      { day: 'Tuesday',   label: 'Tue', open: '18:00', close: '23:30' },
      { day: 'Wednesday', label: 'Wed', open: '18:00', close: '23:30' },
      { day: 'Thursday',  label: 'Thu', open: '18:00', close: '23:30' },
      { day: 'Friday',    label: 'Fri', open: '12:30', close: '00:30' },
      { day: 'Saturday',  label: 'Sat', open: '12:30', close: '00:30' },
      { day: 'Sunday',    label: 'Sun', open: '12:30', close: '23:00' }
    ]
  };

  /* --- taste and dietary vocabulary --------------------------------------- */
  const TAGS = {
    veg:    { label: 'Vegetarian',  short: 'Veg',      tone: 'sage' },
    vegan:  { label: 'Vegan',       short: 'Vegan',    tone: 'sage' },
    gf:     { label: 'Gluten free', short: 'GF',       tone: 'sage' },
    spicy:  { label: 'Chilli heat', short: 'Spiced',   tone: 'clay' },
    chef:   { label: "Chef's table", short: "Chef's",  tone: 'gold' },
    signature: { label: 'Signature', short: 'Signature', tone: 'gold' },
    zero:   { label: 'Zero proof',  short: '0%',       tone: 'sage' }
  };

  const CATEGORIES = [
    { id: 'starters',  name: 'Starters',    note: 'Small plates, built for the middle of the table' },
    { id: 'mains',     name: 'Main Course', note: 'From the wood fire and the coal pit' },
    { id: 'desserts',  name: 'Desserts',    note: 'The last thing you remember' },
    { id: 'beverages', name: 'Beverages',   note: 'Cellar, still room and bar' }
  ];

  /* --- the menu ------------------------------------------------------------ */
  const MENU = [
    /* Starters */
    { id: 'm01', cat: 'starters', img: 'dish-scallop', price: 1450, rating: 4.9, orders: 2140,
      name: 'Charred Scallop, Coconut Malai',
      desc: 'Hand-dived scallop seared over embers, young coconut cream, curry leaf oil, lime ash.',
      tags: ['gf', 'signature'], popular: true },
    { id: 'm02', cat: 'starters', img: 'dish-aubergine', price: 780, rating: 4.7, orders: 1680,
      name: 'Smoked Aubergine, Burnt Garlic',
      desc: 'Aubergine buried in coals until it collapses, hung-curd yoghurt, black garlic, sesame.',
      tags: ['veg', 'gf'] },
    { id: 'm03', cat: 'starters', img: 'dish-oyster', price: 1180, rating: 4.8, orders: 940,
      name: 'Kerala Oyster, Green Mango',
      desc: 'Three oysters from the Malabar coast, raw mango mignonette, kokum pearls.',
      tags: ['gf'] },
    { id: 'm04', cat: 'starters', img: 'dish-beet', price: 690, rating: 4.6, orders: 1320,
      name: 'Tandoori Beetroot, Whipped Feta',
      desc: 'Beets roasted in salt, clay-oven finished, sheep feta, candied walnut, orange.',
      tags: ['veg', 'gf'] },
    { id: 'm05', cat: 'starters', img: 'dish-octopus', price: 1320, rating: 4.8, orders: 1105,
      name: 'Chargrilled Octopus, Malabar Pepper',
      desc: 'Braised eight hours, grilled hard, crushed pepper, burnt lemon, potato skordalia.',
      tags: ['gf', 'spicy'], popular: true },
    { id: 'm06', cat: 'starters', img: 'dish-galouti', price: 840, rating: 4.9, orders: 2410,
      name: 'Wild Mushroom Galouti',
      desc: 'Morel and porcini minced fine with sixteen spices, ghee-toasted brioche, mint.',
      tags: ['veg'], popular: true },

    /* Mains */
    { id: 'm07', cat: 'mains', img: 'dish-shortrib', price: 2150, rating: 4.9, orders: 1890,
      name: '48-Hour Short Rib, Bone Marrow Dal',
      desc: 'Slow-cooked two days, glazed in its own reduction, black dal enriched with marrow.',
      tags: ['signature', 'chef'], popular: true },
    { id: 'm08', cat: 'mains', img: 'dish-lamb', price: 1980, rating: 4.8, orders: 1560,
      name: 'Coal-Roasted Lamb Chops',
      desc: 'Rack from Deccan pasture, kissed by coal, mint chimichurri, charred spring onion.',
      tags: ['gf', 'spicy'] },
    { id: 'm09', cat: 'mains', img: 'dish-truffle', price: 1650, rating: 4.9, orders: 2030,
      name: 'Black Truffle Khichdi',
      desc: 'Aged gobindobhog rice, moong dal, cultured butter, winter truffle shaved at the table.',
      tags: ['veg', 'gf', 'signature'], popular: true },
    { id: 'm10', cat: 'mains', img: 'dish-lobster', price: 2850, rating: 4.9, orders: 780,
      name: 'Saffron Butter Lobster',
      desc: 'Whole lobster split and grilled, Kashmiri saffron butter, fermented chilli, brioche.',
      tags: ['gf', 'chef'] },
    { id: 'm11', cat: 'mains', img: 'dish-morel', price: 1420, rating: 4.7, orders: 890,
      name: 'Kashmiri Morel Pulao',
      desc: 'Guchhi morels foraged in Pahalgam, aged basmati, saffron milk, fried onion.',
      tags: ['veg'] },
    { id: 'm12', cat: 'mains', img: 'dish-seabass', price: 1890, rating: 4.8, orders: 1120,
      name: 'Line-Caught Sea Bass, Coconut Broth',
      desc: 'Day-boat bass, crisp skin, light Alleppey broth, raw banana crisp, curry leaf.',
      tags: ['gf'] },
    { id: 'm13', cat: 'mains', img: 'dish-paneer', price: 1120, rating: 4.6, orders: 1740,
      name: 'Smoked Paneer, Makhani Emulsion',
      desc: 'House-set paneer smoked over hay, tomato emulsion finished with white butter.',
      tags: ['veg', 'gf'] },

    /* Desserts */
    { id: 'm14', cat: 'desserts', img: 'dish-chocolate', price: 680, rating: 4.9, orders: 2260,
      name: 'Valrhona & Cardamom Delice',
      desc: '70% Guanaja, green cardamom, salted caramel centre, cocoa nib tuile.',
      tags: ['veg', 'signature'], popular: true },
    { id: 'm15', cat: 'desserts', img: 'dish-mangotart', price: 640, rating: 4.8, orders: 1410,
      name: 'Alphonso Mango Tart',
      desc: 'Ratnagiri alphonso, brown-butter pastry, vanilla crème, toasted coconut.',
      tags: ['veg'] },
    { id: 'm16', cat: 'desserts', img: 'dish-citrus', price: 620, rating: 4.7, orders: 990,
      name: 'Burnt Citrus Cheesecake',
      desc: 'Basque-style, blowtorched top, kaffir lime curd, candied pomelo.',
      tags: ['veg'] },
    { id: 'm17', cat: 'desserts', img: 'dish-kulfi', price: 520, rating: 4.8, orders: 1830,
      name: 'Rose & Pistachio Kulfi',
      desc: 'Milk reduced four hours, Kannauj rose, Iranian pistachio, silver leaf.',
      tags: ['veg', 'gf'] },
    { id: 'm18', cat: 'desserts', img: 'dish-jamun', price: 590, rating: 4.7, orders: 1290,
      name: 'Gulab Jamun Soufflé',
      desc: 'The classic rebuilt as a soufflé, warm rose syrup poured at the table.',
      tags: ['veg'] },

    /* Beverages */
    { id: 'm19', cat: 'beverages', img: 'dish-oldfashioned', price: 950, rating: 4.9, orders: 2580,
      name: 'Aurelia Old Fashioned',
      desc: 'Single-malt, jaggery, cacao bitters, smoked under glass with cinnamon bark.',
      tags: ['signature'], popular: true },
    { id: 'm20', cat: 'beverages', img: 'dish-ginsour', price: 880, rating: 4.8, orders: 1470,
      name: 'Saffron Gin Sour',
      desc: 'Goan gin, saffron cordial, lime, aquafaba foam, a single drop of bitters.',
      tags: [] },
    { id: 'm21', cat: 'beverages', img: 'dish-kokum', price: 450, rating: 4.7, orders: 1960,
      name: 'Kokum & Basil Cooler',
      desc: 'Konkan kokum, holy basil, black salt, soda. Bright, cold and entirely sober.',
      tags: ['zero', 'veg', 'gf'] },
    { id: 'm22', cat: 'beverages', img: 'dish-coffee', price: 320, rating: 4.8, orders: 3120,
      name: 'Single-Estate Filter Coffee',
      desc: 'Chikmagalur peaberry, roasted weekly, poured the traditional way.',
      tags: ['zero', 'veg', 'gf'], popular: true },
    { id: 'm23', cat: 'beverages', img: 'dish-tea', price: 380, rating: 4.6, orders: 860,
      name: 'Nilgiri First Flush',
      desc: 'Hand-plucked, lightly oxidised, brewed to the minute in a glass pot.',
      tags: ['zero', 'veg', 'gf'] },
    { id: 'm24', cat: 'beverages', img: 'dish-wine', price: 1850, rating: 4.9, orders: 540,
      name: "Sommelier's Wine Flight",
      desc: 'Three pours chosen against your menu, poured and talked through by Devika.',
      tags: ['chef'] }
  ];

  /* --- reviews ------------------------------------------------------------- */
  const REVIEWS = [
    { name: 'Ananya Rao', role: 'Food writer, Mumbai', rating: 5, avatar: 'avatar-1',
      quote: 'The truffle khichdi arrived and the table stopped talking. I have eaten in a lot of dining rooms this year. Nothing else has done that.',
      dish: 'Black Truffle Khichdi', date: '2 weeks ago' },
    { name: 'Mihir Kulkarni', role: 'Regular since opening', rating: 5, avatar: 'avatar-2',
      quote: 'We booked for eight, half of them vegetarian, half of them fussy. Every single plate landed. That is much harder than it sounds.',
      dish: 'Wild Mushroom Galouti', date: '1 month ago' },
    { name: 'Sara D’Souza', role: 'Brought her parents', rating: 5, avatar: 'avatar-3',
      quote: 'My father is seventy-four and deeply suspicious of anything described as "contemporary". He asked for the short rib recipe. He has never asked for a recipe.',
      dish: '48-Hour Short Rib', date: '3 weeks ago' },
    { name: 'Jonathan Lewis', role: 'Corporate host', rating: 5, avatar: 'avatar-4',
      quote: 'I run client dinners here twice a month. The private room, the pacing, the wine flight — it does the work for me before I have said anything.',
      dish: "Sommelier's Wine Flight", date: '5 days ago' },
    { name: 'Priya Nair', role: 'Ordered in', rating: 5, avatar: 'avatar-5',
      quote: 'Delivery arrived forty minutes out, still hot, plated properly in the box. I did not expect a kitchen at this level to care about that.',
      dish: 'Saffron Butter Lobster', date: '1 week ago' },
    { name: 'Tanvi Verma', role: 'Anniversary dinner', rating: 5, avatar: 'avatar-6',
      quote: 'They remembered it was our anniversary from a note I left in the booking form three weeks earlier. Small thing. It made the night.',
      dish: 'Valrhona & Cardamom Delice', date: '2 months ago' }
  ];

  /* --- gallery ------------------------------------------------------------- */
  const GALLERY = [
    { img: 'interior-dining', caption: 'The main room, 7.40pm',     span: 'tall',  cat: 'interior' },
    { img: 'dish-scallop',    caption: 'Scallop, coconut malai',    span: 'wide',  cat: 'food' },
    { img: 'kitchen-pass',    caption: 'The pass, mid-service',     span: '',      cat: 'kitchen' },
    { img: 'dish-shortrib',   caption: 'Short rib, forty-eight hours in', span: '', cat: 'food' },
    { img: 'texture-ember',   caption: 'Embers, banked for the night', span: '',   cat: 'kitchen' },
    { img: 'interior-bar',    caption: 'The bar and the back wall', span: 'tall',  cat: 'interior' },
    { img: 'dish-chocolate',  caption: 'Guanaja and cardamom',      span: '',      cat: 'food' },
    { img: 'texture-herb',    caption: 'Morning herbs, still wet',  span: '',      cat: 'kitchen' },
    { img: 'gallery-room',    caption: 'Corner four, held for regulars', span: 'wide', cat: 'interior' },
    { img: 'dish-lobster',    caption: 'Lobster, saffron butter',   span: '',      cat: 'food' },
    { img: 'texture-char',    caption: 'Char, the point of it all', span: '',      cat: 'kitchen' },
    { img: 'dish-oldfashioned', caption: 'Smoked under glass',      span: '',      cat: 'food' }
  ];

  /* --- supporting copy ----------------------------------------------------- */
  const PILLARS = [
    { icon: 'leaf',   title: 'Grown, not ordered',
      text: 'Ninety-one named farms across six states. Produce is bought the morning it is cut, and the menu is written after the delivery arrives — not before.',
      stat: '91', statLabel: 'partner farms' },
    { icon: 'flame',  title: 'Cooked over fire',
      text: 'No induction on the line. Everything passes through wood, coal or clay, which is slower, harder to control, and the only way to get this flavour.',
      stat: '4', statLabel: 'live fires' },
    { icon: 'clock',  title: 'Served on time',
      text: 'Courses are paced to the table, not the kitchen. Delivery leaves in insulated ceramic and averages thirty-four minutes across Bandra and Khar.',
      stat: '34', statLabel: 'min average delivery' },
    { icon: 'star',   title: 'Held to a standard',
      text: 'A brigade of twenty-two, eleven of whom came from starred kitchens. Every plate is checked at the pass by a head chef before it leaves.',
      stat: '22', statLabel: 'in the brigade' }
  ];

  const ACCOLADES = [
    'Condé Nast Traveller — Top 50 Restaurants in India, 2025',
    'Michelin Guide — Recommended, 2026',
    'Asia’s 50 Best — One To Watch',
    'Times Food Award — Best Fine Dining, Mumbai',
    'World Culinary Awards — India Restaurant of the Year',
    'EazyDiner — 4.9 / 5 across 3,400 reviews'
  ];

  const TIMELINE = [
    { year: '2016', text: 'Ravi Menon leaves a two-star kitchen in Copenhagen and comes home with a notebook and no plan.' },
    { year: '2019', text: 'A twelve-seat supper club runs out of a Bandra flat. It is booked out for fourteen months straight.' },
    { year: '2022', text: 'Aurelia opens on Ashford Lane with one wood oven, one coal pit and forty-four covers.' },
    { year: '2026', text: 'Ninety-one farms, twenty-two cooks, and the same twelve-seat table at the centre of the room.' }
  ];

  const FAQ = [
    { q: 'Do you cater to allergies and dietary restrictions?',
      a: 'Yes, and seriously. Tell us in the booking notes and the kitchen builds around it — we run a separate vegetarian section with its own equipment, and every dish can be traced ingredient by ingredient.' },
    { q: 'Are children welcome?',
      a: 'Very. We keep high chairs, a shorter early-evening menu for under-tens, and the 6.30pm sitting is deliberately quieter and quicker.' },
    { q: 'Can you host a corporate dinner?',
      a: 'The private room seats sixteen, or twenty-four standing, with its own bar and screen. Ask for Devika on the reservations line and she will build a menu against your budget.' },
    { q: 'How far do you deliver?',
      a: 'Bandra, Khar, Santacruz and Juhu directly from our own riders. Everything travels in insulated ceramic and is designed to survive the journey — we do not send anything that will not.' },
    { q: 'What should I wear?',
      a: 'Whatever you would wear to a good dinner. There is no dress code and there never will be.' }
  ];

  return { RESTAURANT, TAGS, CATEGORIES, MENU, REVIEWS, GALLERY, PILLARS, ACCOLADES, TIMELINE, FAQ };
})();
