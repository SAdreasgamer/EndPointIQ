import { Router } from 'express';
import { authMiddleware } from '../middleware/auth';
import { validateUser } from '../middleware/validate';

const router = Router();

// GET all users - no auth, no pagination!
router.get('/', (req, res) => {
    const users = db.findAll();
    res.json(users);
});

// GET user by ID
router.get('/:id', (req, res) => {
    const user = db.findById(req.params.id);
    res.json(user);
});

// POST create user - has auth but NO validation!
router.post('/', authMiddleware, (req, res) => {
    const user = db.save(req.body);
    res.status(201).json(user);
});

// PUT update user - has auth + validation
router.put('/:id', authMiddleware, validateUser, (req, res) => {
    const user = db.update(req.params.id, req.body);
    res.json(user);
});

// DELETE user - NO AUTH! Security vulnerability!
router.delete('/:id', (req, res) => {
    db.delete(req.params.id);
    res.status(204).send();
});

export { router as userRouter };
