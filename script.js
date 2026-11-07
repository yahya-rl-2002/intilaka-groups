const menu = document.querySelector('.menu');
const nav = document.querySelector('nav');
menu?.addEventListener('click', () => {
  const open = nav.style.display === 'flex';
  nav.style.display = open ? 'none' : 'flex';
  if (!open) Object.assign(nav.style, { position: 'absolute', top: '70px', left: '0', right: '0', padding: '22px 8vw', background: '#fff', flexDirection: 'column', gap: '18px', boxShadow: '0 12px 20px #092b621a' });
});
