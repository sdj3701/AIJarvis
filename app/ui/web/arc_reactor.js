/**
 * MARVEL JARVIS 3D HOLOGRAPHIC NEURAL SPHERE
 * Cinematic 3D Gyroscopic Rings, Particle Shell, and Neural Synapses.
 * 
 * - Idle / Speaking: Electric Cyan & Deep Blue (#00e5ff / #0077ff)
 * - Thinking: Warm Amber & Glowing Gold (#ff9d00 / #ff5500) (Matching Movie Screenshot)
 * - Motion: Very slow, smooth, elegant 3D cinematic rotation
 */

const canvas = document.getElementById('reactor-canvas');
const ctx = canvas.getContext('2d');

let currentState = 'idle';

// Color interpolation targets (Hue in degrees)
let currentHue = 195; // Blue / Cyan
let targetHue = 195;
let glowIntensity = 1.0;
let targetGlow = 1.0;

// 3D Angles
let rotX = 0.3;
let rotY = 0;
let rotZ = 0.1;
let time = 0;

// 3D Points on Fibonacci Sphere (Neural Nodes)
const NODE_COUNT = 90;
const sphereNodes = [];
const SPHERE_RADIUS = 130;

for (let i = 0; i < NODE_COUNT; i++) {
  const phi = Math.acos(1 - 2 * (i + 0.5) / NODE_COUNT);
  const theta = Math.PI * (1 + Math.sqrt(5)) * i;
  sphereNodes.push({
    x: SPHERE_RADIUS * Math.sin(phi) * Math.cos(theta),
    y: SPHERE_RADIUS * Math.sin(phi) * Math.sin(theta),
    z: SPHERE_RADIUS * Math.cos(phi),
    pulseOffset: Math.random() * Math.PI * 2,
    size: 1.2 + Math.random() * 1.8
  });
}

// 3D Gyroscopic Rings configuration (Tilts and Radii)
const gyroRings = [
  { radius: 175, tiltX: 0.8, tiltY: 0.2, rotSpeed: 0.002, dashes: [30, 15, 5, 15], width: 1.8 },
  { radius: 155, tiltX: -0.6, tiltY: 0.7, rotSpeed: -0.0025, dashes: [10, 20], width: 1.4 },
  { radius: 135, tiltX: 1.2, tiltY: -0.5, rotSpeed: 0.002, dashes: [60, 30], width: 2.0 },
  { radius: 110, tiltX: -0.9, tiltY: -0.8, rotSpeed: -0.003, dashes: [6, 12], width: 1.2 },
  { radius: 85,  tiltX: 0.3, tiltY: 1.1, rotSpeed: 0.0025, dashes: [40, 40], width: 1.5 },
  { radius: 195, tiltX: 0.1, tiltY: 0.1, rotSpeed: 0.0012, dashes: [8, 24], width: 1.0 }
];

function setReactorState(state) {
  currentState = state;
  const descEl = document.getElementById('reactor-state-desc');
  const badgeEl = document.getElementById('core-mode-text');
  const body = document.body;

  body.classList.remove('state-thinking', 'state-speaking', 'state-listening');

  if (state === 'thinking') {
    // Warm Amber / Golden Orange (Movie Image Style)
    targetHue = 36; // 36° = Gold/Amber/Orange
    targetGlow = 1.6;
    descEl.textContent = 'NEURAL SYNAPSE REASONING IN PROGRESS...';
    descEl.style.color = '#ffaa00';
    badgeEl.textContent = 'CORE // THINKING';
    body.classList.add('state-thinking');
  } else if (state === 'speaking') {
    // Vibrant Electric Blue / Cyan
    targetHue = 195;
    targetGlow = 1.3;
    descEl.textContent = 'TRANSMITTING NEURAL AUDIO / TEXT STREAM';
    descEl.style.color = '#00f0ff';
    badgeEl.textContent = 'CORE // TRANSMITTING';
    body.classList.add('state-speaking');
  } else if (state === 'listening') {
    // Emerald Green / Aqua
    targetHue = 150;
    targetGlow = 1.2;
    descEl.textContent = 'AUDIO SENSOR ACTIVE — LISTENING...';
    descEl.style.color = '#00ff88';
    badgeEl.textContent = 'CORE // LISTENING';
    body.classList.add('state-listening');
  } else if (state === 'error') {
    targetHue = 0; // Red
    targetGlow = 1.5;
    descEl.textContent = 'PROTOCOL EXCEPTION ENCOUNTERED';
    descEl.style.color = '#ff2a4b';
    badgeEl.textContent = 'CORE // ALERT';
  } else {
    // Idle: Calm Cyan / Blue
    targetHue = 195;
    targetGlow = 1.0;
    descEl.textContent = 'AWAITING VOCAL / TEXT DIRECTIVE';
    descEl.style.color = '#00e5ff';
    badgeEl.textContent = 'STANDBY // READY';
  }
}

// 3D Rotation helper
function rotate3D(x, y, z, rx, ry, rz) {
  // Y-axis rotation
  let cosY = Math.cos(ry), sinY = Math.sin(ry);
  let x1 = x * cosY + z * sinY;
  let z1 = -x * sinY + z * cosY;

  // X-axis rotation
  let cosX = Math.cos(rx), sinX = Math.sin(rx);
  let y2 = y * cosX - z1 * sinX;
  let z2 = y * sinX + z1 * cosX;

  // Z-axis rotation
  let cosZ = Math.cos(rz), sinZ = Math.sin(rz);
  let x3 = x1 * cosZ - y2 * sinZ;
  let y3 = x1 * sinZ + y2 * cosZ;

  return { x: x3, y: y3, z: z2 };
}

// Perspective projection helper
function project(p, cx, cy, fov = 400) {
  const scale = fov / (fov + p.z);
  return {
    x: cx + p.x * scale,
    y: cy + p.y * scale,
    scale: scale,
    alpha: Math.max(0.15, Math.min(1.0, (p.z + SPHERE_RADIUS * 1.5) / (SPHERE_RADIUS * 2.5)))
  };
}

function drawHologramSphere() {
  const width = canvas.width;
  const height = canvas.height;
  const cx = width / 2;
  const cy = height / 2;

  ctx.clearRect(0, 0, width, height);

  // Smooth color & glow interpolation (Lerp)
  currentHue += (targetHue - currentHue) * 0.05;
  glowIntensity += (targetGlow - glowIntensity) * 0.05;

  // Very slow, smooth cinematic rotation (0.002 rad/frame)
  const speedMult = currentState === 'thinking' ? 1.2 : 0.8;
  rotY += 0.003 * speedMult;
  rotX = 0.25 + Math.sin(time * 0.3) * 0.06;
  rotZ += 0.001 * speedMult;
  time += 0.012;

  const primaryColor = `hsl(${currentHue}, 100%, 60%)`;
  const brightColor = `hsl(${currentHue}, 100%, 85%)`;
  const dimColor = `hsl(${currentHue}, 80%, 35%)`;

  // 1. Central Pulsing Core Glow (Slow Breathing Wave)
  const pulse = Math.sin(time * 1.5) * 0.12 + 0.88;
  const coreRad = 34 * pulse * glowIntensity;
  const coreGrad = ctx.createRadialGradient(cx, cy, 2, cx, cy, coreRad);
  coreGrad.addColorStop(0, '#ffffff');
  coreGrad.addColorStop(0.3, brightColor);
  coreGrad.addColorStop(0.65, primaryColor);
  coreGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');

  ctx.save();
  ctx.fillStyle = coreGrad;
  ctx.shadowBlur = 32 * glowIntensity;
  ctx.shadowColor = primaryColor;
  ctx.beginPath();
  ctx.arc(cx, cy, coreRad, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  // 2. Draw 3D Gyroscopic Hologram Rings
  gyroRings.forEach((ring, idx) => {
    const ringAngle = time * ring.rotSpeed * 60;
    const segments = 64;
    const pts = [];

    for (let i = 0; i <= segments; i++) {
      const theta = (i / segments) * Math.PI * 2;
      const rx = Math.cos(theta) * ring.radius;
      const ry = Math.sin(theta) * ring.radius;
      const rz = 0;

      // Apply ring's own tilt
      const tilted = rotate3D(rx, ry, rz, ring.tiltX, ring.tiltY, ringAngle);
      // Apply master sphere rotation
      const transformed = rotate3D(tilted.x, tilted.y, tilted.z, rotX, rotY, rotZ);
      const proj = project(transformed, cx, cy);
      pts.push(proj);
    }

    // Render Ring Segments
    ctx.save();
    ctx.strokeStyle = primaryColor;
    ctx.lineWidth = ring.width;
    ctx.shadowBlur = 14 * glowIntensity;
    ctx.shadowColor = primaryColor;
    ctx.setLineDash(ring.dashes);

    ctx.beginPath();
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i];
      if (i === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    }
    ctx.closePath();
    ctx.stroke();

    // Small glowing orbital beads along the ring
    const beadIndex = Math.floor((time * 8 + idx * 10) % segments);
    const bead = pts[beadIndex];
    if (bead) {
      ctx.fillStyle = '#ffffff';
      ctx.shadowBlur = 15;
      ctx.shadowColor = brightColor;
      ctx.beginPath();
      ctx.arc(bead.x, bead.y, 2.5 * bead.scale, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  });

  // 3. Draw 3D Neural Nodes on Sphere & Interconnecting Synapses
  const projectedNodes = sphereNodes.map(node => {
    // Rotate node
    const transformed = rotate3D(node.x, node.y, node.z, rotX, rotY, rotZ);
    const proj = project(transformed, cx, cy);
    return { ...proj, z: transformed.z, node };
  });

  // Sort nodes from back to front for proper depth
  projectedNodes.sort((a, b) => a.z - b.z);

  // Connect close neighbor nodes with faint synaptic threads
  ctx.save();
  ctx.lineWidth = 0.8;
  for (let i = 0; i < projectedNodes.length; i++) {
    const p1 = projectedNodes[i];
    for (let j = i + 1; j < projectedNodes.length; j++) {
      const p2 = projectedNodes[j];
      const dx = p1.x - p2.x;
      const dy = p1.y - p2.y;
      const dist = Math.sqrt(dx * dx + dy * dy);

      if (dist < 48) {
        const lineAlpha = (1 - dist / 48) * 0.35 * Math.min(p1.alpha, p2.alpha);
        ctx.strokeStyle = `hsla(${currentHue}, 100%, 70%, ${lineAlpha})`;
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.stroke();
      }
    }
  }
  ctx.restore();

  // Draw node points
  projectedNodes.forEach(p => {
    const nodePulse = Math.sin(time * 2 + p.node.pulseOffset) * 0.25 + 0.75;
    const r = p.node.size * p.scale * nodePulse;

    ctx.save();
    ctx.globalAlpha = p.alpha;
    ctx.fillStyle = p.z > 0 ? brightColor : dimColor;
    ctx.shadowBlur = p.z > 0 ? 10 * glowIntensity : 2;
    ctx.shadowColor = primaryColor;

    ctx.beginPath();
    ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  });

  requestAnimationFrame(drawHologramSphere);
}

// Start rendering
drawHologramSphere();
